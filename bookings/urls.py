from django.urls import path

from . import views

urlpatterns = [
    path("payment/<uuid:order_id>/", views.payment_checkout, name="payment_checkout"),
    path("payment/verify/", views.verify_payment, name="verify_payment"),
    path("payment/cancel/<uuid:order_id>/", views.cancel_payment, name="cancel_payment"),
    path("payment/status/<uuid:order_id>/", views.payment_status, name="payment_status"),
    path("webhooks/razorpay/", views.razorpay_webhook, name="razorpay_webhook"),
]
