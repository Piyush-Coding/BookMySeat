# Payment & Seat Reservation Architecture

## Overview

BookMySeat uses **Razorpay** for payments and a **2-minute seat reservation** window before payment must complete. Bookings are only created after server-side payment verification.

## Complete Payment Lifecycle

```
1. User selects seats
       ↓
2. POST /movies/theater/<id>/seats/book/
   → SELECT FOR UPDATE on Seat rows (atomic)
   → Create PaymentOrder + SeatReservation (2 min expiry)
   → Create Razorpay Order via API
       ↓
3. Redirect to /bookings/payment/<uuid>/
   → Countdown timer shown
   → User clicks "Pay with Razorpay"
       ↓
4a. SUCCESS (frontend callback)
    → POST /bookings/payment/verify/
    → HMAC signature verified server-side (razorpay.utility.verify_payment_signature)
    → finalize_payment_order() idempotently creates Booking rows
    → Confirmation email sent

4b. SUCCESS (webhook — backup path)
    → POST /bookings/webhooks/razorpay/
    → X-Razorpay-Signature verified with webhook secret
    → Event stored in WebhookEvent (dedup by event_id)
    → finalize_payment_order() if payment.captured

4c. FAILURE / CANCEL
    → User cancels OR payment.failed webhook
    → Reservations released, PaymentOrder marked failed/cancelled

4d. TIMEOUT (2 minutes)
    → Celery beat task release_expired_seat_reservations (every 30s)
    → OR manual: python manage.py release_expired_reservations
    → PaymentOrder → expired, SeatReservation → expired
```

## Idempotency & Fraud Prevention

| Threat | Mitigation |
|--------|-----------|
| **Duplicate webhook delivery** | `WebhookEvent.event_id` unique constraint; duplicate events ignored |
| **Double booking on retry** | `finalize_payment_order()` checks `PaymentOrder.status == paid` and returns existing bookings |
| **Fake frontend success** | Payment signature verified server-side with Razorpay secret — frontend callback alone cannot confirm |
| **Webhook replay attack** | HMAC-SHA256 signature validation using `RAZORPAY_WEBHOOK_SECRET` |
| **Forged webhook payload** | Reject requests without valid `X-Razorpay-Signature` (HTTP 400) |
| **Race on same seat** | PostgreSQL row-level lock via `SELECT FOR UPDATE` inside `transaction.atomic()` |
| **Concurrent reservation** | Partial unique index: only one `active` reservation per seat |
| **Payment after expiry** | Server rejects finalize if `expires_at` passed |

## Consistency Model

- **Pessimistic locking** on Seat rows during reservation and confirmation
- **Atomic transactions** wrap reserve → pay → confirm flows
- Seat unavailable when: `is_booked=True` OR active non-expired `SeatReservation` exists
- **Eventual release** of expired holds via background scheduler (max 30s delay after expiry)

## Environment Variables

```env
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
TICKET_PRICE_INR=150.00
SEAT_RESERVATION_TIMEOUT_SECONDS=120
```

## Commands

```bash
# Run migrations
python manage.py migrate

# Start Celery worker + beat (auto-release expired seats)
celery -A bookmyseat worker -l info -B

# Manual release (if Celery not running)
python manage.py release_expired_reservations
```

## Razorpay Webhook Setup

In Razorpay Dashboard → Webhooks:
- URL: `https://your-domain/bookings/webhooks/razorpay/`
- Secret: same as `RAZORPAY_WEBHOOK_SECRET` in `.env`
- Events: `payment.captured`, `payment.failed`

## Key Files

| File | Purpose |
|------|---------|
| `bookings/models.py` | PaymentOrder, SeatReservation, WebhookEvent |
| `bookings/services.py` | Reservation locking, payment verification, idempotent finalize |
| `bookings/views.py` | Checkout, verify, webhook endpoints |
| `bookings/tasks.py` | Celery auto-release task |
| `movies/views.py` | Seat selection → reserve → redirect to payment |
