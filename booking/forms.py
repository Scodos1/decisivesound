from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Booking, CancellationRequest, CustomerProfile


class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        # Explicit whitelist, not exclude=[...]: status, payment_reference,
        # amount_paid, payment_date, and payment_method must NEVER be
        # customer-settable. An exclude-list already caused a real bug once
        # (a new payment field became silently required on this form) -
        # a whitelist means that can't happen again as the model grows.
        fields = [
            "name", "phone", "email", "event_type", "event_date",
            "state", "address", "guests", "headsets", "duration", "message",
        ]

    def clean_event_date(self):
        event_date = self.cleaned_data["event_date"]
        if event_date < timezone.localdate():
            raise forms.ValidationError("Event date can't be in the past.")
        return event_date


# ---------------------------------------------------------------------
# Customer Portal
# ---------------------------------------------------------------------

class CustomerRegisterForm(UserCreationForm):
    """
    Registration form for the Customer Portal. Email doubles as the
    username (simplest thing that works, and matches how customers
    already identify themselves on bookings) - uniqueness is enforced in
    clean_email() since Django's User.email field isn't unique by default.
    """
    first_name = forms.CharField(max_length=150, label="Full name")
    email = forms.EmailField()
    phone = forms.CharField(max_length=20, required=False)

    class Meta:
        model = User
        fields = ["first_name", "email", "phone", "password1", "password2"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists. Try logging in instead.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["email"]
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        if commit:
            user.save()
            CustomerProfile.objects.create(user=user, phone=self.cleaned_data.get("phone", ""))
        return user


class CustomerProfileForm(forms.Form):
    """Name / phone / email update on the portal's Profile page - kept as
    a plain Form (not a ModelForm) since it writes across both User and
    CustomerProfile. Password changes go through Django's own
    PasswordChangeForm instead (see portal_views.profile)."""
    first_name = forms.CharField(max_length=150, label="Full name")
    email = forms.EmailField()
    phone = forms.CharField(max_length=20, required=False)

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("Another account is already using this email.")
        return email

    def save(self):
        self.user.first_name = self.cleaned_data["first_name"]
        self.user.email = self.cleaned_data["email"]
        self.user.username = self.cleaned_data["email"]
        self.user.save()
        profile, _ = CustomerProfile.objects.get_or_create(user=self.user)
        profile.phone = self.cleaned_data.get("phone", "")
        profile.save()
        return self.user


class CustomerAuthenticationForm(AuthenticationForm):
    """Django's stock AuthenticationForm, relabeled - customers log in
    with their email (which IS their username, set at registration in
    CustomerRegisterForm.save()), so the login page shouldn't say
    'Username'."""
    username = forms.CharField(label="Email", widget=forms.TextInput(attrs={"autofocus": True}))


class CancellationRequestForm(forms.ModelForm):
    class Meta:
        model = CancellationRequest
        fields = ["reason"]
        widgets = {
            "reason": forms.Textarea(attrs={"rows": 4, "placeholder": "Optional - let us know why you'd like to cancel."}),
        }