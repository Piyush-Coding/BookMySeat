"""
Seat reservation and Razorpay payment services.

Consistency model: pessimistic row-level locking (SELECT FOR UPDATE) on Seat rows
inside atomic transactions. A seat is unavailable when is_booked=True OR an active
non-expired SeatReservation exists for another user.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from decimal import Decimal

import razorpay
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from bookings.models import PaymentOrder, SeatReservation, WebhookEvent
from movies.models import Booking, Seat, Theater

logger = logging.getLogger("bookings")

TICKET_PRICE_INR = Decimal(getattr(settings, "TICKET_PRICE_INR", "150.00"))
RESERVATION_TIMEOUT_SECONDS = int(getattr(settings, "SEAT_RESERVATION_TIMEOUT_SECONDS", 120))


def _reservation_expiry():
    return timezone.now() + timezone.timedelta(seconds=RESERVATION_TIMEOUT_SECONDS)


def _razorpay_client():
    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )


def seat_is_unavailable(seat: Seat, *, exclude_user_id: int | None = None) -> bool:
    """Return True if seat cannot be reserved by a new user."""
    if seat.is_booked:
        return True
    qs = SeatReservation.objects.filter(
        seat=seat,
        status=SeatReservation.STATUS_ACTIVE,
        expires_at__gt=timezone.now(),
    )
    if exclude_user_id is not None:
        qs = qs.exclude(user_id=exclude_user_id)
    return qs.exists()


def get_seat_availability_map(theater: Theater, current_user_id: int | None = None) -> dict[int, str]:
    """
    Return {seat_id: state} where state is one of:
    available | booked | reserved_other | reserved_you
    """
    now = timezone.now()
    seats = Seat.objects.filter(theater=theater)
    states = {}

    active_reservations = SeatReservation.objects.filter(
        seat__theater=theater,
        status=SeatReservation.STATUS_ACTIVE,
        expires_at__gt=now,
    ).select_related("seat", "user")

    reservation_by_seat = {r.seat_id: r for r in active_reservations}

    for seat in seats:
        if seat.is_booked:
            states[seat.id] = "booked"
        elif seat.id in reservation_by_seat:
            reservation = reservation_by_seat[seat.id]
            if current_user_id and reservation.user_id == current_user_id:
                states[seat.id] = "reserved_you"
            else:
                states[seat.id] = "reserved_other"
        else:
            states[seat.id] = "available"

    return states


@transaction.atomic
def reserve_seats(user, theater: Theater, seat_ids: list[int]) -> tuple[PaymentOrder | None, list[str]]:
    """
    Atomically lock seats and create a PaymentOrder + SeatReservation rows.
    Returns (payment_order, error_seat_numbers).
    """
    if not seat_ids:
        return None, []

    unique_seat_ids = sorted(set(int(sid) for sid in seat_ids))
    error_seats: list[str] = []

    locked_seats = list(
        Seat.objects.select_for_update()
        .filter(id__in=unique_seat_ids, theater=theater)
        .order_by("id")
    )

    if len(locked_seats) != len(unique_seat_ids):
        return None, ["Invalid seat selection"]

    for seat in locked_seats:
        if seat_is_unavailable(seat, exclude_user_id=user.id):
            error_seats.append(seat.seat_number)

    if error_seats:
        return None, error_seats

    expires_at = _reservation_expiry()
    amount_paise = int(TICKET_PRICE_INR * 100) * len(locked_seats)
    idempotency_key = uuid.uuid4().hex

    payment_order = PaymentOrder.objects.create(
        idempotency_key=idempotency_key,
        user=user,
        theater=theater,
        amount_paise=amount_paise,
        expires_at=expires_at,
        status=PaymentOrder.STATUS_PENDING,
    )

    for seat in locked_seats:
        SeatReservation.objects.create(
            seat=seat,
            user=user,
            payment_order=payment_order,
            status=SeatReservation.STATUS_ACTIVE,
            expires_at=expires_at,
        )

    try:
        client = _razorpay_client()
        razorpay_order = client.order.create(
            {
                "amount": amount_paise,
                "currency": "INR",
                "receipt": f"order_{payment_order.id}",
                "notes": {
                    "idempotency_key": idempotency_key,
                    "payment_order_public_id": str(payment_order.public_id),
                    "user_id": str(user.id),
                    "theater_id": str(theater.id),
                },
            }
        )
        payment_order.razorpay_order_id = razorpay_order["id"]
        payment_order.save(update_fields=["razorpay_order_id", "updated_at"])
    except Exception as exc:
        logger.error("Razorpay order creation failed: %s", exc)
        payment_order.status = PaymentOrder.STATUS_FAILED
        payment_order.failure_reason = str(exc)
        payment_order.save(update_fields=["status", "failure_reason", "updated_at"])
        SeatReservation.objects.filter(payment_order=payment_order).update(
            status=SeatReservation.STATUS_RELEASED
        )
        return None, ["Payment gateway unavailable. Please try again."]

    logger.info(
        "Reserved %s seats for user %s, order %s",
        len(locked_seats),
        user.id,
        payment_order.public_id,
    )
    return payment_order, []


def verify_razorpay_payment_signature(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    client = _razorpay_client()
    try:
        client.utility.verify_payment_signature(
            {
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature,
            }
        )
        return True
    except razorpay.errors.SignatureVerificationError:
        return False


def verify_razorpay_webhook_signature(body: bytes, signature: str) -> bool:
    secret = settings.RAZORPAY_WEBHOOK_SECRET or ""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@transaction.atomic
def finalize_payment_order(
    payment_order: PaymentOrder,
    razorpay_payment_id: str,
    *,
    source: str = "callback",
) -> tuple[list[int], bool]:
    """
    Idempotently confirm payment and create Booking rows.
    Returns (booking_ids, already_processed).
    """
    payment_order = PaymentOrder.objects.select_for_update().get(pk=payment_order.pk)

    if payment_order.status == PaymentOrder.STATUS_PAID:
        booking_ids = list(
            Booking.objects.filter(payment_order=payment_order).values_list("id", flat=True)
        )
        return booking_ids, True

    if payment_order.status in (
        PaymentOrder.STATUS_CANCELLED,
        PaymentOrder.STATUS_EXPIRED,
        PaymentOrder.STATUS_FAILED,
    ):
        raise ValueError(f"Payment order is {payment_order.status}")

    if timezone.now() > payment_order.expires_at:
        _expire_payment_order(payment_order)
        raise ValueError("Payment window expired")

    reservations = list(
        SeatReservation.objects.select_for_update()
        .filter(
            payment_order=payment_order,
            status=SeatReservation.STATUS_ACTIVE,
            expires_at__gt=timezone.now(),
        )
        .select_related("seat")
    )

    if not reservations:
        raise ValueError("No active seat reservations for this order")

    booking_ids: list[int] = []
    for reservation in reservations:
        seat = Seat.objects.select_for_update().get(pk=reservation.seat_id)
        if seat.is_booked:
            raise ValueError(f"Seat {seat.seat_number} was already booked")

        booking = Booking.objects.create(
            user=payment_order.user,
            seat=seat,
            movie=payment_order.theater.movie,
            theater=payment_order.theater,
            payment_order=payment_order,
        )
        seat.is_booked = True
        seat.save(update_fields=["is_booked"])
        reservation.status = SeatReservation.STATUS_CONFIRMED
        reservation.save(update_fields=["status"])
        booking_ids.append(booking.id)

    payment_order.status = PaymentOrder.STATUS_PAID
    payment_order.razorpay_payment_id = razorpay_payment_id
    payment_order.paid_at = timezone.now()
    payment_order.save(
        update_fields=["status", "razorpay_payment_id", "paid_at", "updated_at"]
    )

    logger.info(
        "Payment finalized via %s for order %s, bookings %s",
        source,
        payment_order.public_id,
        booking_ids,
    )
    return booking_ids, False


@transaction.atomic
def cancel_payment_order(payment_order: PaymentOrder) -> None:
    payment_order = PaymentOrder.objects.select_for_update().get(pk=payment_order.pk)
    if payment_order.status != PaymentOrder.STATUS_PENDING:
        return
    payment_order.status = PaymentOrder.STATUS_CANCELLED
    payment_order.save(update_fields=["status", "updated_at"])
    SeatReservation.objects.filter(
        payment_order=payment_order,
        status=SeatReservation.STATUS_ACTIVE,
    ).update(status=SeatReservation.STATUS_RELEASED)


@transaction.atomic
def _expire_payment_order(payment_order: PaymentOrder) -> None:
    payment_order.status = PaymentOrder.STATUS_EXPIRED
    payment_order.save(update_fields=["status", "updated_at"])
    SeatReservation.objects.filter(
        payment_order=payment_order,
        status=SeatReservation.STATUS_ACTIVE,
    ).update(status=SeatReservation.STATUS_EXPIRED)


def release_expired_reservations() -> dict[str, int]:
    """Release all expired active reservations and pending payment orders."""
    now = timezone.now()
    expired_orders = PaymentOrder.objects.filter(
        status=PaymentOrder.STATUS_PENDING,
        expires_at__lte=now,
    )
    order_count = expired_orders.count()
    for order in expired_orders:
        with transaction.atomic():
            _expire_payment_order(order)

    stale_reservations = SeatReservation.objects.filter(
        status=SeatReservation.STATUS_ACTIVE,
        expires_at__lte=now,
    )
    reservation_count = stale_reservations.update(status=SeatReservation.STATUS_EXPIRED)

    return {"orders_expired": order_count, "reservations_expired": reservation_count}


@transaction.atomic
def process_razorpay_webhook(event_id: str, event_type: str, payload: dict) -> str:
    """
    Process a verified Razorpay webhook idempotently.
    Returns status message.
    """
    if WebhookEvent.objects.filter(event_id=event_id).exists():
        return "duplicate"

    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    order_entity = payload.get("payload", {}).get("order", {}).get("entity", {})

    razorpay_order_id = payment_entity.get("order_id") or order_entity.get("id")
    razorpay_payment_id = payment_entity.get("id")

    payment_order = None
    if razorpay_order_id:
        payment_order = PaymentOrder.objects.filter(
            razorpay_order_id=razorpay_order_id
        ).first()

    WebhookEvent.objects.create(
        event_id=event_id,
        event_type=event_type,
        payment_order=payment_order,
        payload=payload,
    )

    if event_type == "payment.captured" and payment_order and razorpay_payment_id:
        try:
            finalize_payment_order(
                payment_order,
                razorpay_payment_id,
                source="webhook",
            )
            return "processed"
        except ValueError as exc:
            logger.warning("Webhook finalize skipped: %s", exc)
            return f"skipped:{exc}"

    if event_type in ("payment.failed",) and payment_order:
        payment_order = PaymentOrder.objects.select_for_update().get(pk=payment_order.pk)
        if payment_order.status == PaymentOrder.STATUS_PENDING:
            payment_order.status = PaymentOrder.STATUS_FAILED
            payment_order.failure_reason = payment_entity.get("error_description", "Payment failed")
            payment_order.save(update_fields=["status", "failure_reason", "updated_at"])
            SeatReservation.objects.filter(
                payment_order=payment_order,
                status=SeatReservation.STATUS_ACTIVE,
            ).update(status=SeatReservation.STATUS_RELEASED)
        return "failed_recorded"

    return "ignored"
