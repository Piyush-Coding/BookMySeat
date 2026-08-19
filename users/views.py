import threading
import logging
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.models import User
from .forms import UserRegisterform, UserUpdateForm
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.contrib import messages
from django.conf import settings
from movies.models import Movie, Booking

logger = logging.getLogger('bookings')


def home(request):
    movies = Movie.objects.all()
    return render(request, 'users/home.html', {'movies': movies})


def register(request):
    if request.method == "POST":
        form = UserRegisterform(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False  # Account inactive until email verification link clicked
            user.save()

            current_site = get_current_site(request)
            domain = current_site.domain
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            activation_url = f"http://{domain}/users/activate/{uid}/{token}/"

            context = {
                'user': user,
                'activation_url': activation_url,
                'domain': domain,
            }
            html_content = render_to_string('emails/activation_email.html', context)
            plain_content = f"Hi {user.username},\n\nPlease verify your email address to complete registration on BookMySeat by clicking the link below:\n\n{activation_url}\n\nThank you!"
            subject = "Verify Your Email - BookMySeat"
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or 'noreply@bookmyseat.com'

            def _send_verification_email():
                try:
                    email_msg = EmailMultiAlternatives(subject, plain_content, from_email, [user.email])
                    email_msg.attach_alternative(html_content, "text/html")
                    email_msg.send(fail_silently=False)
                    logger.info(f"Verification email successfully sent to {user.email}")
                except Exception as e:
                    logger.error(f"Failed to send email verification to {user.email}. Error: {str(e)}")

            threading.Thread(target=_send_verification_email, daemon=False).start()

            return render(request, 'users/email_verification_sent.html', {'email': user.email})
    else:
        form = UserRegisterform()
    return render(request, 'users/register.html', {'forms': form})


def activate_account(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, "Your email has been verified successfully! Welcome to BookMySeat.")
        return redirect('profile')
    else:
        return render(request, 'users/email_verification_invalid.html')


def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('/')
        else:
            username_input = request.POST.get('username')
            if username_input:
                try:
                    inactive_user = User.objects.get(username=username_input, is_active=False)
                    messages.error(request, "Your email is not verified yet. Please check your inbox for the activation link.")
                except User.DoesNotExist:
                    pass
    else:
        form = AuthenticationForm()
    return render(request, 'users/login.html', {'forms': form})


@login_required
def profile(request):
    bookings = Booking.objects.filter(user=request.user)
    if request.method == "POST":
        u_form = UserUpdateForm(request.POST, instance=request.user)
        if u_form.is_valid():
            u_form.save()
            return redirect("profile")
    else:
        u_form = UserUpdateForm(instance=request.user)
    return render(request, 'users/profile.html', {'u_forms': u_form, 'bookings': bookings})


@login_required
def reset_password(request):
    if request.method == "POST":
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = PasswordChangeForm(user=request.user)
    return render(request, 'users/reset_password.html', {'forms': form})
