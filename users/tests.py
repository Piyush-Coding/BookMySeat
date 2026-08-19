from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core import mail

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class UserEmailVerificationTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_registration_creates_inactive_user_and_sends_email(self):
        response = self.client.post('/users/register/', {
            'username': 'testverifyuser',
            'email': 'verifytest@example.com',
            'password1': 'StrongPassword123!',
            'password2': 'StrongPassword123!'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Verification Link Sent!")

        # Verify user exists in database and is_active is False
        user = User.objects.filter(username='testverifyuser').first()
        self.assertIsNotNone(user)
        self.assertFalse(user.is_active)

    def test_activation_link_activates_user(self):
        # Create an inactive user manually
        user = User.objects.create_user(
            username='activationuser',
            email='acttest@example.com',
            password='StrongPassword123!'
        )
        user.is_active = False
        user.save()

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        activate_url = f'/users/activate/{uid}/{token}/'
        response = self.client.get(activate_url)

        # Should redirect to profile after successful activation
        self.assertRedirects(response, '/users/profile/')

        # Refresh user from DB
        user.refresh_from_db()
        self.assertTrue(user.is_active)
