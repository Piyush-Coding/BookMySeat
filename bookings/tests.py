from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from unittest.mock import patch
from movies.models import Movie, Theater, Seat, Booking
from bookings.tasks import send_booking_confirmation_email

class EmailConfirmationTaskTest(TestCase):
    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username='testuser', 
            email='testuser@example.com', 
            password='testpassword'
        )
        
        # Create test movie
        self.movie = Movie.objects.create(
            name='Inception',
            rating=9.0,
            cast='Leonardo DiCaprio',
            description='A thief who steals corporate secrets through the use of dream-sharing technology.'
        )
        
        # Create test theater and showtime
        self.theater = Theater.objects.create(
            name='IMAX Screen 1',
            movie=self.movie,
            time=timezone.now() + timezone.timedelta(days=1)
        )
        
        # Create test seats
        self.seat1 = Seat.objects.create(
            theater=self.theater,
            seat_number='A1',
            is_booked=True
        )
        self.seat2 = Seat.objects.create(
            theater=self.theater,
            seat_number='A2',
            is_booked=True
        )
        
        # Create test bookings
        self.booking1 = Booking.objects.create(
            user=self.user,
            seat=self.seat1,
            movie=self.movie,
            theater=self.theater
        )
        self.booking2 = Booking.objects.create(
            user=self.user,
            seat=self.seat2,
            movie=self.movie,
            theater=self.theater
        )
        
        self.booking_ids = [self.booking1.id, self.booking2.id]

    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_send_booking_confirmation_email_task_success(self, mock_send):
        """
        Verify the Celery task executes successfully, renders details correctly,
        and triggers Django's mail system.
        """
        # Execute the task synchronously (using task function directly, not via delay)
        result = send_booking_confirmation_email(
            booking_ids=self.booking_ids,
            recipient_email='testuser@example.com',
            payment_id='PAYID-TEST123456',
            total_amount='INR 300.00'
        )
        
        self.assertEqual(result, "Successfully sent confirmation email to testuser@example.com")
        self.assertTrue(mock_send.called)
        
    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_send_booking_confirmation_email_no_bookings(self, mock_send):
        """
        Verify the task returns early and doesn't send mail if booking IDs are invalid.
        """
        result = send_booking_confirmation_email(
            booking_ids=[99999, 88888],
            recipient_email='testuser@example.com'
        )
        self.assertTrue("No bookings found" in result)
        self.assertFalse(mock_send.called)
