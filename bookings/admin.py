from django.contrib import admin

from .models import PaymentOrder, SeatReservation, WebhookEvent


class SeatReservationInline(admin.TabularInline):
    model = SeatReservation
    extra = 0
    readonly_fields = ["seat", "user", "status", "reserved_at", "expires_at"]


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = [
        "public_id",
        "user",
        "theater",
        "status",
        "amount_paise",
        "razorpay_order_id",
        "expires_at",
        "paid_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = ["public_id", "idempotency_key", "razorpay_order_id", "razorpay_payment_id"]
    readonly_fields = ["public_id", "idempotency_key", "created_at", "updated_at"]
    inlines = [SeatReservationInline]


@admin.register(SeatReservation)
class SeatReservationAdmin(admin.ModelAdmin):
    list_display = ["seat", "user", "payment_order", "status", "expires_at"]
    list_filter = ["status"]
    search_fields = ["seat__seat_number", "user__username"]


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["event_id", "event_type", "payment_order", "processed_at"]
    list_filter = ["event_type"]
    search_fields = ["event_id"]
