"""
Customer Portal - everything a logged-in customer can do that an
anonymous visitor can't: see their bookings, download their own
quotations/invoices, request a cancellation, and manage their profile.

Security model: every view here either requires login (@login_required)
or is part of the public auth flow (register/login/password reset). Every
booking lookup is scoped with `user=request.user` so one customer can
never load another customer's booking, quotation, or invoice - a
mismatched booking id 404s exactly the same as a nonexistent one, so
this never leaks whether a given booking id belongs to someone else.
"""
import logging

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import documents
from . import notifications
from .constants import DASHBOARD_STATUS_COLORS, PAYMENT_STATUS_GROUPS, payment_status_for
from .forms import CancellationRequestForm, CustomerProfileForm, CustomerRegisterForm
from .models import Booking, CancellationRequest, CustomerProfile

logger = logging.getLogger(__name__)

WHATSAPP_NUMBER = "2348033807067"


# ---------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------

def register(request):
    if request.user.is_authenticated:
        return redirect("portal_dashboard")

    if request.method == "POST":
        form = CustomerRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Bridge for legacy/anonymous bookings: attach any existing
            # booking rows whose email matches the new account, so a
            # customer who booked before the portal existed immediately
            # sees their history rather than an empty dashboard.
            linked = Booking.objects.filter(
                email__iexact=user.email, user__isnull=True,
            ).update(user=user)

            login(request, user)
            if linked:
                messages.success(
                    request,
                    f"Welcome, {user.first_name}! We've linked {linked} existing "
                    f"booking{'s' if linked != 1 else ''} to your new account.",
                )
            else:
                messages.success(request, f"Welcome, {user.first_name}! Your account is ready.")
            return redirect("portal_dashboard")
    else:
        form = CustomerRegisterForm()

    return render(request, "booking/portal/register.html", {"form": form})


# ---------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------

@login_required(login_url="portal_login")
def dashboard(request):
    today = timezone.localdate()
    bookings = request.user.bookings.all().order_by("-event_date")

    upcoming = [b for b in bookings if b.event_date >= today and b.status != Booking.STATUS_CANCELLED]
    upcoming.sort(key=lambda b: b.event_date)
    history = [b for b in bookings if b.event_date < today or b.status in (Booking.STATUS_CANCELLED, Booking.STATUS_COMPLETED)]

    next_event = upcoming[0] if upcoming else None
    notification_list = request.user.notifications.all()[:8]
    unread_count = request.user.notifications.filter(is_read=False).count()

    booking_rows = [
        {
            "booking": b,
            "payment_status": payment_status_for(b),
            "status_color": DASHBOARD_STATUS_COLORS.get(b.status, "#666"),
        }
        for b in bookings
    ]

    context = {
        "bookings": booking_rows,
        "upcoming_count": len(upcoming),
        "history_count": len(history),
        "next_event": next_event,
        "notifications": notification_list,
        "unread_count": unread_count,
        "today": today,
    }
    return render(request, "booking/portal/dashboard.html", context)


@login_required(login_url="portal_login")
@require_POST
def mark_notifications_read(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    next_url = request.POST.get("next") or reverse("portal_dashboard")
    return redirect(next_url)


# ---------------------------------------------------------------------
# Booking detail
# ---------------------------------------------------------------------

@login_required(login_url="portal_login")
def booking_detail(request, booking_id):
    booking_obj = get_object_or_404(Booking, pk=booking_id, user=request.user)

    pending_cancellation = booking_obj.cancellation_requests.filter(
        status=CancellationRequest.STATUS_PENDING
    ).first()
    can_request_cancellation = (
        booking_obj.status not in (Booking.STATUS_CANCELLED, Booking.STATUS_COMPLETED)
        and pending_cancellation is None
    )

    whatsapp_message = f"Hi, I'd like to ask about my booking #{booking_obj.id} ({booking_obj.event_type}, {booking_obj.event_date})."
    from urllib.parse import quote
    whatsapp_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(whatsapp_message)}"

    context = {
        "booking": booking_obj,
        "payment_status": payment_status_for(booking_obj),
        "status_color": DASHBOARD_STATUS_COLORS.get(booking_obj.status, "#666"),
        "pending_cancellation": pending_cancellation,
        "can_request_cancellation": can_request_cancellation,
        "cancellation_form": CancellationRequestForm(),
        "whatsapp_url": whatsapp_url,
        "full_amount": booking_obj.amount_due(Booking.PAYMENT_FULL) if booking_obj.can_pay_full else None,
    }
    return render(request, "booking/portal/booking_detail.html", context)


@login_required(login_url="portal_login")
def quotation_pdf(request, booking_id):
    booking_obj = get_object_or_404(Booking, pk=booking_id, user=request.user)
    if not booking_obj.quotation_number:
        messages.info(request, "Your quotation isn't ready yet - we'll notify you as soon as it is.")
        return redirect("portal_booking_detail", booking_id=booking_obj.id)
    pdf_bytes = documents.quotation_pdf_bytes(booking_obj)
    if pdf_bytes is None:
        messages.error(request, "Couldn't generate that PDF right now - please try again shortly.")
        return redirect("portal_booking_detail", booking_id=booking_obj.id)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="Quotation-{booking_obj.quotation_number}.pdf"'
    return response


@login_required(login_url="portal_login")
def invoice_pdf(request, booking_id):
    booking_obj = get_object_or_404(Booking, pk=booking_id, user=request.user)
    if not booking_obj.invoice_number:
        messages.info(request, "Your invoice isn't ready yet - it's generated automatically once a payment is received.")
        return redirect("portal_booking_detail", booking_id=booking_obj.id)
    pdf_bytes = documents.invoice_pdf_bytes(booking_obj)
    if pdf_bytes is None:
        messages.error(request, "Couldn't generate that PDF right now - please try again shortly.")
        return redirect("portal_booking_detail", booking_id=booking_obj.id)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="Invoice-{booking_obj.invoice_number}.pdf"'
    return response


@login_required(login_url="portal_login")
@require_POST
def request_cancellation(request, booking_id):
    booking_obj = get_object_or_404(Booking, pk=booking_id, user=request.user)

    if booking_obj.status in (Booking.STATUS_CANCELLED, Booking.STATUS_COMPLETED):
        messages.error(request, "This booking can no longer be cancelled.")
        return redirect("portal_booking_detail", booking_id=booking_obj.id)

    if booking_obj.cancellation_requests.filter(status=CancellationRequest.STATUS_PENDING).exists():
        messages.info(request, "You already have a pending cancellation request for this booking.")
        return redirect("portal_booking_detail", booking_id=booking_obj.id)

    form = CancellationRequestForm(request.POST)
    if form.is_valid():
        cancellation_request = form.save(commit=False)
        cancellation_request.booking = booking_obj
        cancellation_request.requested_by = request.user
        cancellation_request.save()
        notifications.notify_cancellation_requested(cancellation_request)
        notifications.send_cancellation_requested_business(cancellation_request)
        messages.success(request, "Your cancellation request has been submitted for review. We'll let you know the outcome.")
    else:
        messages.error(request, "Couldn't submit that request - please try again.")
    return redirect("portal_booking_detail", booking_id=booking_obj.id)


# ---------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------

@login_required(login_url="portal_login")
def profile(request):
    profile_obj, _ = CustomerProfile.objects.get_or_create(user=request.user)

    if request.method == "POST" and request.POST.get("form_name") == "profile":
        profile_form = CustomerProfileForm(
            request.POST, user=request.user,
            initial={"first_name": request.user.first_name, "email": request.user.email, "phone": profile_obj.phone},
        )
        password_form = PasswordChangeForm(request.user)
        if profile_form.is_valid():
            profile_form.save()
            messages.success(request, "Your profile has been updated.")
            return redirect("portal_profile")
    elif request.method == "POST" and request.POST.get("form_name") == "password":
        profile_form = CustomerProfileForm(
            user=request.user,
            initial={"first_name": request.user.first_name, "email": request.user.email, "phone": profile_obj.phone},
        )
        password_form = PasswordChangeForm(request.user, request.POST)
        if password_form.is_valid():
            user = password_form.save()
            update_session_auth_hash(request, user)  # keep the customer logged in after changing their own password
            messages.success(request, "Your password has been changed.")
            return redirect("portal_profile")
    else:
        profile_form = CustomerProfileForm(
            user=request.user,
            initial={"first_name": request.user.first_name, "email": request.user.email, "phone": profile_obj.phone},
        )
        password_form = PasswordChangeForm(request.user)

    return render(request, "booking/portal/profile.html", {
        "profile_form": profile_form, "password_form": password_form,
    })
