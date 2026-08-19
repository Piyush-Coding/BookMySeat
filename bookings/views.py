import json
import logging
import threading

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from bookings.models import PaymentOrder, SeatReservation
from bookings.services import (
    TICKET_PRICE_INR,
    RESERVATION_TIMEOUT_SECONDS,
    cancel_payment_order,
    finalize_payment_order,
    process_razorpay_webhook,
    verify_razorpay_payment_signature,
    verify_razorpay_webhook_signature,
)
from movies.views import _dispatch_booking_email

logger = logging.getLogger("bookings")


@login_required(login_url="/login/")
def payment_checkout(request, order_id):
    payment_order = get_object_or_404(
        PaymentOrder.objects.select_related("theater", "theater__movie", "user"),
        public_id=order_id,
        user=request.user,
    )

    if payment_order.status == PaymentOrder.STATUS_PAID:
        return redirect("profile")

    if payment_order.status != PaymentOrder.STATUS_PENDING:
        return render(
            request,
            "bookings/payment_result.html",
            {
                "success": False,
                "message": f"Payment is {payment_order.get_status_display().lower()}.",
                "payment_order": payment_order,
            },
        )

    if timezone.now() > payment_order.expires_at:
        cancel_payment_order(payment_order)
        return render(
            request,
            "bookings/payment_result.html",
            {
                "success": False,
                "message": "Your seat reservation has expired. Please select seats again.",
                "payment_order": payment_order,
            },
        )

    reservations = SeatReservation.objects.filter(
        payment_order=payment_order,
        status=SeatReservation.STATUS_ACTIVE,
    ).select_related("seat")

    seat_numbers = [r.seat.seat_number for r in reservations]
    seconds_remaining = max(
        0,
        int((payment_order.expires_at - timezone.now()).total_seconds()),
    )

    return render(
        request,
        "bookings/payment_checkout.html",
        {
            "payment_order": payment_order,
            "theater": payment_order.theater,
            "movie": payment_order.theater.movie,
            "seat_numbers": seat_numbers,
            "seat_count": len(seat_numbers),
            "ticket_price": TICKET_PRICE_INR,
            "total_amount": payment_order.amount_paise / 100,
            "razorpay_key_id": settings.RAZORPAY_KEY_ID,
            "seconds_remaining": seconds_remaining,
            "reservation_timeout": RESERVATION_TIMEOUT_SECONDS,
        },
    )


@login_required(login_url="/login/")
@require_POST
def verify_payment(request):
    razorpay_order_id = request.POST.get("razorpay_order_id", "").strip()
    razorpay_payment_id = request.POST.get("razorpay_payment_id", "").strip()
    razorpay_signature = request.POST.get("razorpay_signature", "").strip()
    order_public_id = request.POST.get("order_public_id", "").strip()

    payment_order = get_object_or_404(
        PaymentOrder,
        public_id=order_public_id,
        user=request.user,
    )

    if not verify_razorpay_payment_signature(
        razorpay_order_id, razorpay_payment_id, razorpay_signature
    ):
        logger.warning(
            "Invalid payment signature for order %s user %s",
            payment_order.public_id,
            request.user.id,
        )
        return render(
            request,
            "bookings/payment_result.html",
            {
                "success": False,
                "message": "Payment verification failed. Invalid signature.",
                "payment_order": payment_order,
            },
        )

    try:
        booking_ids, already_processed = finalize_payment_order(
            payment_order,
            razorpay_payment_id,
            source="callback",
        )
    except ValueError as exc:
        return render(
            request,
            "bookings/payment_result.html",
            {
                "success": False,
                "message": str(exc),
                "payment_order": payment_order,
            },
        )

    if booking_ids and not already_processed:
        total_amount = f"INR {payment_order.amount_paise / 100:.2f}"
        threading.Thread(
            target=_dispatch_booking_email,
            args=(
                booking_ids,
                request.user.email,
                razorpay_payment_id,
                total_amount,
            ),
            daemon=False,
        ).start()

    return render(
        request,
        "bookings/payment_result.html",
        {
            "success": True,
            "message": "Payment successful! Your tickets are confirmed.",
            "payment_order": payment_order,
            "booking_ids": booking_ids,
        },
    )


@login_required(login_url="/login/")
@require_POST
def cancel_payment(request, order_id):
    payment_order = get_object_or_404(
        PaymentOrder,
        public_id=order_id,
        user=request.user,
    )
    cancel_payment_order(payment_order)
    return redirect("book_seats", theater_id=payment_order.theater_id)


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    signature = request.headers.get("X-Razorpay-Signature", "")
    body = request.body

    if not verify_razorpay_webhook_signature(body, signature):
        logger.warning("Rejected Razorpay webhook: invalid signature")
        return HttpResponse(status=400)

    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse(status=400)

    event_id = payload.get("id") or payload.get("event_id")
    event_type = payload.get("event", "")

    if not event_id:
        return HttpResponse(status=400)

    result = process_razorpay_webhook(event_id, event_type, payload)
    logger.info("Webhook %s (%s): %s", event_id, event_type, result)
    return JsonResponse({"status": result})


@login_required(login_url="/login/")
@require_GET
def payment_status(request, order_id):
    payment_order = get_object_or_404(
        PaymentOrder,
        public_id=order_id,
        user=request.user,
    )
    seconds_remaining = max(
        0,
        int((payment_order.expires_at - timezone.now()).total_seconds()),
    )
    return JsonResponse(
        {
            "status": payment_order.status,
            "seconds_remaining": seconds_remaining,
            "expired": seconds_remaining == 0
            and payment_order.status == PaymentOrder.STATUS_PENDING,
        }
    )
