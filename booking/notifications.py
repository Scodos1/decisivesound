"""
All outbound booking emails live here - both the "new booking" emails
(business notification + customer confirmation) and the status-change
emails triggered automatically by Booking.save() whenever status changes.

Every send_* function is best-effort: wrapped in try/except, logs on
failure, never raises. A dead mail server must never lose a booking or
block the customer from reaching WhatsApp.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMessage, send_mail

from .models import Booking, Notification

logger = logging.getLogger(__name__)

# Where the "new booking" / business-facing notifications go.
BOOKING_NOTIFICATION_EMAIL = "decisivesound8@gmail.com"


def _notify_customer(booking, notif_type, message):
    """Creates the in-portal Notification row alongside an email, so the
    Customer Dashboard's Recent Notifications panel and the customer's
    inbox always agree. No-op for bookings with no linked account (most
    legacy/anonymous bookings) - there's nowhere in the portal to show it.
    Best-effort like every send_* function here: a DB hiccup on this must
    never block the email it's paired with."""
    if not booking.user_id:
        return
    try:
        Notification.objects.create(
            user_id=booking.user_id, booking=booking, notif_type=notif_type, message=message,
        )
    except Exception:
        logger.exception("Failed to create portal notification (%s) for booking #%s", notif_type, booking.id)


def _send(subject, body, to_email, *, context_id):
    """Shared best-effort send wrapper used by every function below."""
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Failed to send email (%s) to %s", context_id, to_email)


# ---------------------------------------------------------------------
# New booking emails
# ---------------------------------------------------------------------

def send_new_booking_notification(booking):
    """Best-effort email to the business inbox with the full booking."""
    subject = f"New booking: {booking.name} — {booking.event_type} ({booking.event_date})"
    body = "New booking request — Decisive Sound NG\n\n" + booking.details_text()
    _send(subject, body, BOOKING_NOTIFICATION_EMAIL, context_id=f"new-booking-business #{booking.id}")


def send_customer_confirmation_email(booking):
    """Best-effort confirmation to the customer, only if they gave an email."""
    if not booking.email:
        return

    subject = "We've received your booking — Decisive Sound NG"
    body = (
        f"Hi {booking.name},\n\n"
        "Thanks for booking with Decisive Sound NG! We've received your request "
        "and saved your details. Our team will reach out on WhatsApp shortly to "
        "confirm everything.\n\n"
        "Here's a summary of what you sent us:\n\n"
        + booking.details_text()
        + "\n\nIf anything above looks wrong, just reply to this email or reach "
        "us on WhatsApp and we'll sort it out.\n\n"
        "— Decisive Sound NG"
    )
    _send(subject, body, booking.email, context_id=f"new-booking-customer #{booking.id}")


# ---------------------------------------------------------------------
# Status-change emails
# ---------------------------------------------------------------------
# Keyed by the status the booking just moved INTO. Any transition that
# lands on that status fires the associated email - matches the spec's
# framing (e.g. "Pending -> Confirmed" is really just "whenever a booking
# becomes Confirmed"). STATUS_PENDING has no entry: arriving at Pending
# only ever happens on creation (handled separately above), or a manual
# revert, which doesn't warrant a customer email.

def _confirmed_email(booking):
    subject = "Your booking has been confirmed — Decisive Sound NG"
    body = (
        f"Hi {booking.name},\n\n"
        "Good news — your booking has been confirmed! Your date and equipment "
        "are reserved for:\n\n"
        f"Event:  {booking.event_type}\n"
        f"Date:   {booking.event_date}\n"
        f"State:  {booking.state}\n\n"
        "Next step is securing your reservation with a deposit — our team will "
        "be in touch on WhatsApp with the details.\n\n"
        "— Decisive Sound NG"
    )
    return subject, body


def _deposit_paid_email(booking):
    subject = "Deposit received — your booking is secured"
    body = (
        f"Hi {booking.name},\n\n"
        "We've received your deposit and your reservation is now secured. "
        "Your equipment has been reserved for:\n\n"
        f"Event:  {booking.event_type}\n"
        f"Date:   {booking.event_date}\n\n"
        f"Estimated total for your event: "
        f"{'₦' + format(booking.estimated_total(), ',') if booking.state == 'Lagos' else 'To be confirmed'}\n\n"
        "A detailed receipt will follow separately. Thanks for booking with us!\n\n"
        "— Decisive Sound NG"
    )
    return subject, body


def _fully_paid_email(booking):
    subject = "Payment complete — you're all set!"
    body = (
        f"Hi {booking.name},\n\n"
        "Your payment is complete and you're fully set for your event:\n\n"
        f"Event:  {booking.event_type}\n"
        f"Date:   {booking.event_date}\n\n"
        "There's nothing further needed from you on the payment side. We'll "
        "be in touch as your event date approaches.\n\n"
        "— Decisive Sound NG"
    )
    return subject, body


def _completed_email(booking):
    subject = "Thank you for booking with Decisive Sound NG!"
    body = (
        f"Hi {booking.name},\n\n"
        "Thank you for choosing Decisive Sound NG for your "
        f"{booking.event_type.lower()}! We hope everyone had a great time.\n\n"
        "We'd love to hear how it went — reply to this email or send us a "
        "quick note on WhatsApp with your feedback. It genuinely helps us "
        "improve for the next event.\n\n"
        "Hope to work with you again soon!\n\n"
        "— Decisive Sound NG"
    )
    return subject, body


def _cancelled_email(booking):
    subject = "Your booking has been cancelled"
    body = (
        f"Hi {booking.name},\n\n"
        "This confirms your booking has been cancelled:\n\n"
        f"Event:  {booking.event_type}\n"
        f"Date:   {booking.event_date}\n\n"
        "If this wasn't expected or you'd like to rebook, just reach out to "
        "us on WhatsApp and we'll help sort it out.\n\n"
        "— Decisive Sound NG"
    )
    return subject, body


STATUS_EMAIL_BUILDERS = {
    Booking.STATUS_CONFIRMED: _confirmed_email,
    Booking.STATUS_DEPOSIT_PAID: _deposit_paid_email,
    Booking.STATUS_FULLY_PAID: _fully_paid_email,
    Booking.STATUS_COMPLETED: _completed_email,
    Booking.STATUS_CANCELLED: _cancelled_email,
}

# Which in-portal Notification type each status transition maps to - a
# customer-facing short message for the Dashboard's notification feed,
# separate from the full email body above.
STATUS_NOTIFICATION_TYPES = {
    Booking.STATUS_CONFIRMED: (Notification.TYPE_BOOKING_CONFIRMED, "Your booking has been confirmed."),
    Booking.STATUS_DEPOSIT_PAID: (Notification.TYPE_PAYMENT_RECEIVED, "Deposit received - your booking is secured."),
    Booking.STATUS_FULLY_PAID: (Notification.TYPE_PAYMENT_RECEIVED, "Payment complete - you're all set!"),
    Booking.STATUS_COMPLETED: (Notification.TYPE_BOOKING_COMPLETED, "Your event is complete. Thank you for booking with us!"),
    Booking.STATUS_CANCELLED: (Notification.TYPE_BOOKING_CANCELLED, "Your booking has been cancelled."),
}


def send_status_change_email(booking, old_status, new_status):
    """
    Called automatically by Booking.save() whenever status actually
    changes. Only emails the customer if they gave an email address -
    same as the other customer-facing emails. Also creates the matching
    in-portal Notification (see STATUS_NOTIFICATION_TYPES), independent
    of whether an email address is on file.
    """
    if old_status == new_status:
        return

    notif = STATUS_NOTIFICATION_TYPES.get(new_status)
    if notif:
        _notify_customer(booking, notif[0], f"{notif[1]} ({booking.event_type}, {booking.event_date})")

    if not booking.email:
        return

    builder = STATUS_EMAIL_BUILDERS.get(new_status)
    if builder is None:
        return

    subject, body = builder(booking)
    _send(subject, body, booking.email, context_id=f"status {old_status}->{new_status} #{booking.id}")


# ---------------------------------------------------------------------
# Payment emails (booking/views.py, after a verified Paystack payment)
# ---------------------------------------------------------------------

def send_payment_receipt(booking, transaction):
    """Receipt to the customer for a verified payment - includes the
    amount actually paid, the payment reference, and booking reference,
    per the spec. Only sent if they gave an email; the in-portal
    notification fires regardless."""
    payment_label = "Full payment" if transaction.payment_type == Booking.PAYMENT_FULL else "Deposit"
    _notify_customer(
        booking, Notification.TYPE_PAYMENT_RECEIVED,
        f"{payment_label} of ₦{transaction.amount:,} received - thank you!",
    )

    if not booking.email:
        return

    subject = f"Payment receipt — {payment_label} received"
    body = (
        f"Hi {booking.name},\n\n"
        f"We've received your {payment_label.lower()} — thank you!\n\n"
        "─── Receipt ───\n"
        f"Booking reference:  #{booking.id}\n"
        f"Payment type:       {payment_label}\n"
        f"Amount paid:        ₦{transaction.amount:,}\n"
        f"Payment reference:  {transaction.reference}\n"
        f"Payment date:       {booking.payment_date.strftime('%d %b %Y, %I:%M %p') if booking.payment_date else '—'}\n"
        f"Payment method:     {booking.payment_method}\n"
        "────────────────\n\n"
        f"Event:  {booking.event_type}\n"
        f"Date:   {booking.event_date}\n\n"
        "— Decisive Sound NG"
    )
    _send(subject, body, booking.email, context_id=f"payment-receipt #{booking.id}")


def send_payment_notification_business(booking, transaction):
    """Best-effort email to the business inbox with the payment details -
    customer info, amount paid, payment reference."""
    payment_label = "Full payment" if transaction.payment_type == Booking.PAYMENT_FULL else "Deposit"
    subject = f"Payment received: {booking.name} — ₦{transaction.amount:,} ({payment_label})"
    body = (
        f"A payment was just verified for booking #{booking.id}.\n\n"
        f"Customer:           {booking.name}\n"
        f"Phone:              {booking.phone}\n"
        f"Email:              {booking.email or '—'}\n"
        f"Payment type:       {payment_label}\n"
        f"Amount paid:        ₦{transaction.amount:,}\n"
        f"Payment reference:  {transaction.reference}\n"
        f"Payment date:       {booking.payment_date.strftime('%d %b %Y, %I:%M %p') if booking.payment_date else '—'}\n\n"
        f"Event:  {booking.event_type}\n"
        f"Date:   {booking.event_date}\n"
        f"Booking status is now: {booking.status}"
    )
    _send(subject, body, BOOKING_NOTIFICATION_EMAIL, context_id=f"payment-business #{booking.id}")


# ---------------------------------------------------------------------
# Dashboard-initiated emails
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# Quotation & invoice emails (booking/documents.py builds the PDFs)
# ---------------------------------------------------------------------

def send_quotation_email(booking):
    """Emails the quotation PDF to the customer. Called automatically the
    moment a booking becomes Confirmed (see Booking.save()), and manually
    from the dashboard's Generate Quote / Email Quotation actions.
    Returns True/False (unlike the best-effort sends above) so a manual
    dashboard trigger can tell the admin it failed - the automatic call
    from save() simply ignores the return value."""
    if not booking.email:
        return False

    from . import documents
    pdf_bytes = documents.quotation_pdf_bytes(booking)
    if not pdf_bytes:
        logger.error("Quotation PDF generation failed for booking #%s", booking.id)
        return False

    expiry = booking.quotation_expiry_date.strftime('%d %b %Y') if booking.quotation_expiry_date else "—"
    subject = f"Your quotation from Decisive Sound NG — #{booking.quotation_number}"
    body = (
        f"Hi {booking.name},\n\n"
        "Please find attached your quotation for the following event:\n\n"
        f"Event:  {booking.event_type}\n"
        f"Date:   {booking.event_date}\n\n"
        f"Quotation #{booking.quotation_number}, valid until {expiry}.\n\n"
        "Let us know if you have any questions, or reply here / reach us "
        "on WhatsApp to proceed with payment.\n\n"
        "— Decisive Sound NG"
    )
    try:
        email = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [booking.email])
        email.attach(f"Quotation-{booking.quotation_number}.pdf", pdf_bytes, "application/pdf")
        email.send(fail_silently=False)
        booking.mark_quotation_sent()
        _notify_customer(
            booking, Notification.TYPE_QUOTATION_GENERATED,
            f"Quotation #{booking.quotation_number} is ready to view/download.",
        )
        return True
    except Exception:
        logger.exception("Failed to send quotation email for booking #%s", booking.id)
        return False


def send_invoice_email(booking):
    """Emails the invoice PDF to the customer. Called automatically after
    every verified payment (booking/views.py, alongside the payment
    receipt), and manually from the dashboard's Email Invoice action.
    Returns True/False, same reasoning as send_quotation_email above."""
    if not booking.email:
        return False

    from . import documents
    pdf_bytes = documents.invoice_pdf_bytes(booking)
    if not pdf_bytes:
        logger.error("Invoice PDF generation failed for booking #%s", booking.id)
        return False

    subject = f"Your invoice from Decisive Sound NG — #{booking.invoice_number}"
    body = (
        f"Hi {booking.name},\n\n"
        "Please find attached your invoice for the following event:\n\n"
        f"Event:  {booking.event_type}\n"
        f"Date:   {booking.event_date}\n\n"
        f"Invoice #{booking.invoice_number}\n"
        f"Amount paid:  ₦{booking.amount_paid:,}\n\n"
        "— Decisive Sound NG"
    )
    try:
        email = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [booking.email])
        email.attach(f"Invoice-{booking.invoice_number}.pdf", pdf_bytes, "application/pdf")
        email.send(fail_silently=False)
        booking.mark_invoice_sent()
        _notify_customer(
            booking, Notification.TYPE_INVOICE_GENERATED,
            f"Invoice #{booking.invoice_number} is ready to view/download.",
        )
        return True
    except Exception:
        logger.exception("Failed to send invoice email for booking #%s", booking.id)
        return False


def send_custom_email(booking, subject, body):
    """Free-form email an admin sends to a customer from the dashboard
    (booking/views.py:dashboard_send_email). Returns True/False instead of
    silently swallowing the error like the other best-effort sends here,
    because the admin is waiting on this one and needs to know if it
    failed so they can fall back to WhatsApp/phone."""
    if not booking.email:
        return False
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[booking.email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Dashboard custom email failed for booking #%s", booking.id)
        return False


# ---------------------------------------------------------------------
# Customer Portal - cancellation requests (booking/portal_views.py,
# booking/admin.py's approve/reject actions)
# ---------------------------------------------------------------------

def notify_cancellation_requested(cancellation_request):
    """In-portal notification confirming the customer's own cancellation
    request was received (separate from send_cancellation_requested_business,
    which is the business-facing email)."""
    booking = cancellation_request.booking
    _notify_customer(
        booking, Notification.TYPE_CANCELLATION_REQUESTED,
        "Your cancellation request was received and is pending review.",
    )


def send_cancellation_requested_business(cancellation_request):
    """Best-effort email to the business inbox when a customer requests
    a cancellation - staff review/approve it from Django Admin."""
    booking = cancellation_request.booking
    subject = f"Cancellation requested: {booking.name} — booking #{booking.id}"
    body = (
        f"{booking.name} has requested to cancel their booking.\n\n"
        f"Event:   {booking.event_type}\n"
        f"Date:    {booking.event_date}\n"
        f"Status:  {booking.status}\n"
        f"Reason:  {cancellation_request.reason or '—'}\n\n"
        "Review and approve/reject this from Django Admin > Cancellation Requests."
    )
    _send(subject, body, BOOKING_NOTIFICATION_EMAIL, context_id=f"cancellation-requested #{booking.id}")


def send_cancellation_decision(cancellation_request):
    """Emails the customer once staff approve or reject their
    cancellation request, and creates the matching in-portal
    notification. Called from admin.py's approve/reject actions."""
    booking = cancellation_request.booking
    approved = cancellation_request.status == cancellation_request.STATUS_APPROVED

    _notify_customer(
        booking, Notification.TYPE_CANCELLATION_DECIDED,
        "Your cancellation request was approved." if approved
        else "Your cancellation request was not approved.",
    )

    if not booking.email:
        return

    if approved:
        subject = "Your cancellation request has been approved"
        body = (
            f"Hi {booking.name},\n\n"
            "Your request to cancel the following booking has been approved:\n\n"
            f"Event:  {booking.event_type}\n"
            f"Date:   {booking.event_date}\n\n"
            "Note: this is a separate confirmation from the general cancellation email you may "
            "also receive.\n\n"
            "— Decisive Sound NG"
        )
    else:
        note = f"\n\nNote from our team: {cancellation_request.admin_note}" if cancellation_request.admin_note else ""
        subject = "Your cancellation request was not approved"
        body = (
            f"Hi {booking.name},\n\n"
            "We've reviewed your request to cancel the following booking, and we're not able to "
            "approve it as-is:\n\n"
            f"Event:  {booking.event_type}\n"
            f"Date:   {booking.event_date}"
            f"{note}\n\n"
            "Reach out to us on WhatsApp and we'll help sort out the best option for you.\n\n"
            "— Decisive Sound NG"
        )
    _send(subject, body, booking.email, context_id=f"cancellation-decision #{booking.id}")
