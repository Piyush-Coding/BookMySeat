import uuid

from django.conf import settings
from django.db import models


class PaymentOrder(models.Model):
    """Razorpay payment order linked to a seat reservation batch."""

    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_EXPIRED = "expired"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PAID, "Paid"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_EXPIRED, "Expired"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    idempotency_key = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payment_orders",
    )
    theater = models.ForeignKey(
        "movies.Theater",
        on_delete=models.CASCADE,
        related_name="payment_orders",
    )
    razorpay_order_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    amount_paise = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    expires_at = models.DateTimeField(db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "expires_at"]),
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        return f"PaymentOrder {self.public_id} ({self.status})"


class SeatReservation(models.Model):
    """Temporary seat hold (default 2 minutes) before payment completes."""

    STATUS_ACTIVE = "active"
    STATUS_CONFIRMED = "confirmed"
    STATUS_RELEASED = "released"
    STATUS_EXPIRED = "expired"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_RELEASED, "Released"),
        (STATUS_EXPIRED, "Expired"),
    ]

    seat = models.ForeignKey(
        "movies.Seat",
        on_delete=models.CASCADE,
        related_name="reservations",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="seat_reservations",
    )
    payment_order = models.ForeignKey(
        PaymentOrder,
        on_delete=models.CASCADE,
        related_name="seat_reservations",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    reserved_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["seat", "status", "expires_at"]),
            models.Index(fields=["payment_order", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["seat"],
                condition=models.Q(status="active"),
                name="unique_active_seat_reservation",
            ),
        ]

    def __str__(self):
        return f"{self.seat.seat_number} reserved by {self.user.username} ({self.status})"


class WebhookEvent(models.Model):
    """Processed Razorpay webhook events for idempotency / replay protection."""

    event_id = models.CharField(max_length=128, unique=True, db_index=True)
    event_type = models.CharField(max_length=64)
    payment_order = models.ForeignKey(
        PaymentOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="webhook_events",
    )
    payload = models.JSONField(default=dict)
    processed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.event_type} ({self.event_id})"
