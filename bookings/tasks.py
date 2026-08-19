import logging
import datetime
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings

logger = logging.getLogger('bookings')


@shared_task
def release_expired_seat_reservations():
    """Background job: release seat holds past the 2-minute payment window."""
    from bookings.services import release_expired_reservations

    result = release_expired_reservations()
    logger.info("Released expired reservations: %s", result)
    return result


@shared_task(bind=True, max_retries=3)
def send_booking_confirmation_email(self_or_ids, *args, **kwargs):
    """
    Asynchronously sends a movie booking confirmation HTML email to the user.
    Retries up to 3 times with exponential backoff if sending fails.
    Supports both Celery task invocation and direct function calls.
    """
    from movies.models import Booking

    if hasattr(self_or_ids, 'request'):
        self_task = self_or_ids
        booking_ids = args[0] if args else kwargs.get('booking_ids')
        recipient_email = args[1] if len(args) > 1 else kwargs.get('recipient_email')
        payment_id = args[2] if len(args) > 2 else kwargs.get('payment_id')
        total_amount = args[3] if len(args) > 3 else kwargs.get('total_amount')
    else:
        self_task = None
        booking_ids = self_or_ids
        recipient_email = args[0] if args else kwargs.get('recipient_email')
        payment_id = args[1] if len(args) > 1 else kwargs.get('payment_id')
        total_amount = args[2] if len(args) > 2 else kwargs.get('total_amount')

    if isinstance(booking_ids, (int, str)):
        booking_ids = [booking_ids]

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    booking_ids_str = ", ".join(str(bid) for bid in (booking_ids or []))

    logger.info(
        f"Attempting to send booking confirmation email. "
        f"Booking ID(s): [{booking_ids_str}], Recipient: {recipient_email}, "
        f"Payment ID: {payment_id or 'N/A'}, Timestamp: {timestamp}"
    )

    try:
        bookings = list(
            Booking.objects.filter(id__in=booking_ids or []).select_related(
                'movie', 'theater', 'seat', 'user'
            )
        )

        if not bookings:
            logger.error(
                f"Booking retrieval failed. No bookings found for IDs: [{booking_ids_str}]. "
                f"Recipient: {recipient_email}, Timestamp: {timestamp}"
            )
            return f"No bookings found for IDs: {booking_ids}"

        first_booking = bookings[0]
        username = first_booking.user.username
        movie_name = first_booking.movie.name
        theater_name = first_booking.theater.name
        show_time = first_booking.theater.time

        show_date_str = show_time.strftime('%A, %B %d, %Y')
        show_time_str = show_time.strftime('%I:%M %p')

        seat_numbers = [b.seat.seat_number for b in bookings]
        seat_numbers_str = ", ".join(seat_numbers)

        context = {
            'username': username,
            'movie_name': movie_name,
            'theater_name': theater_name,
            'show_date': show_date_str,
            'show_time': show_time_str,
            'seat_numbers': seat_numbers_str,
            'booking_id': booking_ids_str,
            'payment_id': payment_id or "N/A",
            'total_amount': total_amount or "N/A",
        }

        html_content = render_to_string('emails/booking_confirmation.html', context)
        text_content = strip_tags(html_content)

        subject = f"Booking Confirmed: {movie_name} - {theater_name}"
        from_email = settings.DEFAULT_FROM_EMAIL or 'noreply@bookmyseat.com'

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=[recipient_email]
        )
        email.attach_alternative(html_content, "text/html")
        email.send(fail_silently=False)

        logger.info(
            f"Email successfully sent. Booking ID(s): [{booking_ids_str}], "
            f"Recipient: {recipient_email}, Payment ID: {payment_id or 'N/A'}, "
            f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return f"Successfully sent confirmation email to {recipient_email}"

    except Exception as exc:
        if self_task and hasattr(self_task, 'request'):
            current_retry = getattr(self_task.request, 'retries', 0)
            retry_msg = f"Retry attempt {current_retry + 1}/3"

            logger.warning(
                f"Failed to send booking confirmation email. {retry_msg}. "
                f"Booking ID(s): [{booking_ids_str}], Recipient: {recipient_email}, "
                f"Reason: {str(exc)}, Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            if current_retry >= getattr(self_task, 'max_retries', 3):
                logger.error(
                    f"FINAL FAILURE: Max retries reached. Email could not be sent. "
                    f"Booking ID(s): [{booking_ids_str}], Recipient: {recipient_email}, "
                    f"Reason: {str(exc)}"
                )
                raise exc

            countdown = (2 ** current_retry) * 30
            raise self_task.retry(exc=exc, countdown=countdown)
        else:
            logger.error(
                f"Failed direct email dispatch for Booking IDs [{booking_ids_str}] to {recipient_email}. "
                f"Reason: {str(exc)}"
            )
            raise exc
