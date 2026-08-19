from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm

class UserRegisterform(UserCreationForm):
    email = forms.EmailField(
        required=True,
        help_text="Required. A verification link will be sent to this email address."
    )

    class Meta:
        model = User
        fields = ['username', 'email']


class UserUpdateForm(forms.ModelForm):
    email = forms.EmailField()
    class Meta:
        model = User
        fields = ['username', 'email']

class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["password"]