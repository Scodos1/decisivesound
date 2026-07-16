import calendar as calendar_module
import csv
import json
import logging
import uuid
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import quote

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import analytics
from . import documents
from . import notifications
from . import paystack
from . import reports
from .constants import DASHBOARD_STATUS_COLORS, PAYMENT_STATUS_GROUPS, payment_status_for
from .forms import BookingForm
from .models import Booking, EQUIPMENT_HEADSET, EquipmentInventory, GalleryImage, PaymentTransaction

logger = logging.getLogger(__name__)

# Same WhatsApp number the old client-side script used (js/booking.js -> WA_NUMBER).
WHATSAPP_NUMBER = "2348033807067"

# How long a duplicate (same phone + event_date + headsets) submission is
# treated as a re-submit of the same booking rather than a new one.
DUPLICATE_WINDOW_MINUTES = 5

# How many upcoming events to list on the dashboard.
DASHBOARD_UPCOMING_LIMIT = 10

# How many bookings the filterable "Recent Bookings" table shows per page.
DASHBOARD_BOOKINGS_PAGE_SIZE = 15

# Kept as a local alias so the rest of this file (written before the
# constants module existed) doesn't need touching everywhere it calls
# _payment_status_for(...).
_payment_status_for = payment_status_for




def home(request):
    gallery_images = GalleryImage.objects.filter(is_active=True)[:6]
    return render(request, "booking/index.html", {"gallery_images": gallery_images})


def about(request):
    return render(request, "booking/about.html")


def services(request):
    return render(request, "booking/services.html")


def gallery(request):
    images = GalleryImage.objects.filter(is_active=True)
    return render(request, "booking/gallery.html", {"images": images})


def equipment(request):
    return render(request, "booking/equipment.html")


def terms(request):
    return render(request, "booking/terms.html")


def contact(request):
    return render(request, "booking/contact.html")


def booking(request):
    if request.method == "POST":
        form = BookingForm(request.POST)

        if form.is_valid():
            booking_obj, is_new = _get_or_create_booking(form, request.user)

            # Booking is already committed to the DB at this point. Both
            # emails below are best-effort side effects — if either fails
            # for any reason (bad SMTP creds, network hiccup, provider
            # downtime), it's logged and skipped. The booking must not be
            # lost and the customer must still reach WhatsApp.
            if is_new:
                notifications.send_new_booking_notification(booking_obj)
                notifications.send_customer_confirmation_email(booking_obj)

            # Redirect (Post/Redirect/Get) so refreshing or back-buttoning
            # the success page never re-submits the form.
            return redirect("booking_success", booking_id=booking_obj.id)
        # form invalid: fall through and re-render with errors below
    elif request.user.is_authenticated:
        # Pre-fill name/phone/email for a logged-in customer booking again.
        form = BookingForm(initial={
            "name": request.user.get_full_name() or request.user.first_name,
            "email": request.user.email,
            "phone": getattr(getattr(request.user, "customer_profile", None), "phone", ""),
        })
    else:
        form = BookingForm()

    return render(request, "booking/booking.html", {"form": form})


def _get_or_create_booking(form, user=None):
    """
    Save the booking, unless an identical one (same phone, event_date and
    headset count) was already created in the last few minutes — in that
    case reuse it instead of writing a duplicate row. Covers double-clicks,
    slow connections triggering a second submit, etc.

    Returns (booking, is_new) so callers can skip side effects (like the
    notification emails) on a reused/duplicate booking. If `user` is an
    authenticated customer, the (new or reused) booking is linked to
    their Customer Portal account.
    """
    cutoff = timezone.now() - timedelta(minutes=DUPLICATE_WINDOW_MINUTES)
    existing = (
        Booking.objects.filter(
            phone=form.cleaned_data["phone"],
            event_date=form.cleaned_data["event_date"],
            headsets=form.cleaned_data["headsets"],
            created_at__gte=cutoff,
        )
        .order_by("-created_at")
        .first()
    )

    is_authenticated_user = user is not None and user.is_authenticated

    if existing:
        if is_authenticated_user and not existing.user_id:
            existing.user = user
            existing.save(skip_status_email=True)
        return existing, False

    booking_obj = form.save(commit=False)
    if is_authenticated_user:
        booking_obj.user = user
    booking_obj.save()
    return booking_obj, True


def booking_success(request, booking_id):
    booking_obj = get_object_or_404(Booking, id=booking_id)

    whatsapp_message = (
        "New booking request — Decisive Sound NG\n\n" + booking_obj.details_text()
    )
    whatsapp_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(whatsapp_message)}"

    return render(
        request,
        "booking/booking_success.html",
        {"booking": booking_obj, "whatsapp_url": whatsapp_url},
    )


@staff_member_required
def admin_dashboard(request):
    """
    Staff-only business dashboard: summary cards, revenue, a placeholder
    inventory snapshot, upcoming events, notifications, and a searchable/
    filterable/paginated bookings table with quick actions. Linked from
    the Booking changelist in the Django admin (see admin.py).
    """
    today = timezone.localdate()
    all_bookings = Booking.objects.all()

    # ---- Summary cards -------------------------------------------------
    total_bookings = all_bookings.count()
    counts_by_status = dict(
        all_bookings.values("status").annotate(count=Count("id")).values_list("status", "count")
    )
    status_breakdown = [
        {
            "label": label,
            "count": counts_by_status.get(choice, 0),
            "color": DASHBOARD_STATUS_COLORS.get(choice, "#666"),
        }
        for choice, label in Booking.STATUS_CHOICES
    ]

    # ---- Revenue summary -------------------------------------------------
    # Revenue this month: verified payments (of any type) received this
    # calendar month - actual cash in, not estimates.
    month_start = today.replace(day=1)
    revenue_this_month = PaymentTransaction.objects.filter(
        status=PaymentTransaction.STATUS_SUCCESS, verified_at__date__gte=month_start,
    ).aggregate(total=Sum("amount"))["total"] or 0

    # Deposits received: all verified deposit payments, all time.
    deposits_received = PaymentTransaction.objects.filter(
        status=PaymentTransaction.STATUS_SUCCESS, payment_type=Booking.PAYMENT_DEPOSIT,
    ).aggregate(total=Sum("amount"))["total"] or 0

    # Outstanding payments: remaining balance on active (not cancelled,
    # not yet fully settled) bookings where the total is actually a known
    # number - can't say what's "outstanding" on a price still TBC.
    outstanding_payments = sum(
        b.estimated_total() - b.amount_paid
        for b in all_bookings.exclude(
            status__in=[Booking.STATUS_CANCELLED, Booking.STATUS_FULLY_PAID, Booking.STATUS_COMPLETED]
        )
        if b.full_price_known
    )

    # ---- Inventory summary (Headsets - the only type tied to bookings) --
    headset_inventory = EquipmentInventory.objects.filter(equipment_type=EQUIPMENT_HEADSET).first()
    inventory_configured = headset_inventory is not None
    if headset_inventory:
        inventory_total = headset_inventory.total_quantity
        inventory_maintenance = headset_inventory.maintenance_quantity
        reserved_headsets = headset_inventory.reserved_today()
        inventory_available = headset_inventory.available_today()
    else:
        inventory_total = inventory_maintenance = reserved_headsets = inventory_available = 0

    # ---- Upcoming events -------------------------------------------------
    upcoming_qs = all_bookings.filter(
        event_date__gte=today,
    ).exclude(status=Booking.STATUS_CANCELLED).order_by("event_date")
    upcoming_count = upcoming_qs.count()
    upcoming_events = upcoming_qs[:DASHBOARD_UPCOMING_LIMIT]

    # ---- Calendar overview (see dashboard_calendar for the full grid) --
    week_from_tomorrow = today + timedelta(days=7)
    month_end = date(today.year, today.month, calendar_module.monthrange(today.year, today.month)[1])
    active_bookings = all_bookings.exclude(status=Booking.STATUS_CANCELLED)
    todays_events_count = active_bookings.filter(event_date=today).count()
    upcoming_this_week_count = active_bookings.filter(
        event_date__gt=today, event_date__lte=week_from_tomorrow,
    ).count()
    bookings_this_month_qs = active_bookings.filter(event_date__gte=month_start, event_date__lte=month_end)
    bookings_this_month_count = bookings_this_month_qs.count()
    busy_days_this_month_count = sum(
        1 for count in bookings_this_month_qs.values("event_date")
        .annotate(count=Count("id")).values_list("count", flat=True)
        if count > 1
    )

    # ---- Notifications -----------------------------------------------
    tomorrow = today + timedelta(days=1)
    notification_items = []
    pending_count = counts_by_status.get(Booking.STATUS_PENDING, 0)
    if pending_count:
        notification_items.append(f"{pending_count} pending booking{'s' if pending_count != 1 else ''}")
    awaiting_verification = PaymentTransaction.objects.filter(status=PaymentTransaction.STATUS_PENDING).count()
    if awaiting_verification:
        notification_items.append(
            f"{awaiting_verification} payment{'s' if awaiting_verification != 1 else ''} awaiting verification"
        )
    events_tomorrow = all_bookings.filter(event_date=tomorrow).exclude(status=Booking.STATUS_CANCELLED).count()
    if events_tomorrow:
        notification_items.append(f"{events_tomorrow} event{'s' if events_tomorrow != 1 else ''} tomorrow")
    if inventory_maintenance:
        notification_items.append(f"{inventory_maintenance} headsets under maintenance")

    # ---- Search & filters (drive the "Recent Bookings" table below) ----
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    payment_status_filter = request.GET.get("payment_status", "").strip()
    event_type_filter = request.GET.get("event_type", "").strip()
    state_filter = request.GET.get("state", "").strip()
    date_filter = request.GET.get("event_date", "").strip()

    filtered = all_bookings.order_by("-created_at")
    if q:
        query = Q(name__icontains=q) | Q(phone__icontains=q)
        if q.isdigit():
            query |= Q(id=int(q))
        filtered = filtered.filter(query)
    if status_filter:
        filtered = filtered.filter(status=status_filter)
    if payment_status_filter and payment_status_filter in PAYMENT_STATUS_GROUPS:
        filtered = filtered.filter(status__in=PAYMENT_STATUS_GROUPS[payment_status_filter])
    if event_type_filter:
        filtered = filtered.filter(event_type=event_type_filter)
    if state_filter:
        filtered = filtered.filter(state=state_filter)
    if date_filter:
        filtered = filtered.filter(event_date=date_filter)

    filtered_count = filtered.count()
    page_number = request.GET.get("page", "1")
    try:
        page_number = max(int(page_number), 1)
    except ValueError:
        page_number = 1
    start = (page_number - 1) * DASHBOARD_BOOKINGS_PAGE_SIZE
    end = start + DASHBOARD_BOOKINGS_PAGE_SIZE
    page_bookings = list(filtered[start:end])
    for b in page_bookings:
        b.payment_status_label = _payment_status_for(b)
    has_next_page = end < filtered_count
    has_prev_page = page_number > 1

    # Preserve the current filters across pagination/sort links.
    querydict = request.GET.copy()
    querydict.pop("page", None)
    filters_querystring = querydict.urlencode()

    distinct_states = all_bookings.exclude(state="").values_list("state", flat=True).distinct().order_by("state")

    context = {
        "total_bookings": total_bookings,
        "status_breakdown": status_breakdown,
        "counts_by_status": counts_by_status,
        "upcoming_count": upcoming_count,
        "upcoming_events": upcoming_events,
        "todays_events_count": todays_events_count,
        "upcoming_this_week_count": upcoming_this_week_count,
        "bookings_this_month_count": bookings_this_month_count,
        "busy_days_this_month_count": busy_days_this_month_count,
        "revenue_this_month": revenue_this_month,
        "outstanding_payments": outstanding_payments,
        "deposits_received": deposits_received,
        "inventory_total": inventory_total,
        "inventory_reserved": reserved_headsets,
        "inventory_available": inventory_available,
        "inventory_maintenance": inventory_maintenance,
        "inventory_configured": inventory_configured,
        "notification_items": notification_items,
        "bookings": page_bookings,
        "filtered_count": filtered_count,
        "page_number": page_number,
        "has_next_page": has_next_page,
        "has_prev_page": has_prev_page,
        "filters_querystring": filters_querystring,
        "q": q,
        "status_filter": status_filter,
        "payment_status_filter": payment_status_filter,
        "event_type_filter": event_type_filter,
        "state_filter": state_filter,
        "date_filter": date_filter,
        "status_choices": Booking.STATUS_CHOICES,
        "payment_status_choices": list(PAYMENT_STATUS_GROUPS.keys()),
        "event_type_choices": Booking.EVENT_TYPES,
        "state_choices": distinct_states,
    }
    return render(request, "booking/admin_dashboard.html", context)


@staff_member_required
@require_POST
def dashboard_booking_action(request, booking_id):
    """Quick-action buttons on the dashboard: Confirm or Cancel a booking
    in one click, without leaving for Django Admin. Anything more involved
    (editing details, other status transitions) still goes through Admin,
    per admin.py's fuller action set."""
    booking_obj = get_object_or_404(Booking, pk=booking_id)
    action = request.POST.get("action")

    if action == "confirm":
        if booking_obj.status != Booking.STATUS_PENDING:
            messages.error(request, f"Booking #{booking_obj.id} isn't Pending, so it can't be confirmed from here.")
        else:
            booking_obj.status = Booking.STATUS_CONFIRMED
            reason = booking_obj.insufficient_headset_availability()
            if reason:
                messages.error(request, reason)
            else:
                booking_obj.save()
                messages.success(request, f"Booking #{booking_obj.id} confirmed.")
    elif action == "cancel":
        if booking_obj.status in (Booking.STATUS_CANCELLED, Booking.STATUS_COMPLETED):
            messages.error(request, f"Booking #{booking_obj.id} is already {booking_obj.status} and can't be cancelled.")
        else:
            booking_obj.status = Booking.STATUS_CANCELLED
            booking_obj.save()
            messages.success(request, f"Booking #{booking_obj.id} cancelled.")
    else:
        messages.error(request, "Unknown action.")

    next_url = request.POST.get("next") or reverse("admin_dashboard")
    return redirect(next_url)


@staff_member_required
def dashboard_calendar(request):
    """'View Calendar' quick action: a full monthly calendar grid with every
    booking plotted on its event date, a same-day drill-down, inventory
    conflict highlighting, and the same status/payment/event-type/state
    filters as the main dashboard table. Month/year come from ?year=&month=
    (defaulting to the current month); Prev/Next/Today links and the
    month+year jump form all just re-GET this view with new values."""
    today = timezone.localdate()

    try:
        year = int(request.GET.get("year", today.year))
    except ValueError:
        year = today.year
    try:
        month = int(request.GET.get("month", today.month))
    except ValueError:
        month = today.month
    # Normalize out-of-range month (e.g. Prev from January, Next from
    # December) into a rollover to the adjacent year, rather than 400ing.
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1

    first_of_month = date(year, month, 1)
    days_in_month = calendar_module.monthrange(year, month)[1]
    last_of_month = date(year, month, days_in_month)

    prev_month_date = first_of_month - timedelta(days=1)
    next_month_date = last_of_month + timedelta(days=1)

    # ---- Filters (mirror the dashboard's Search & Filter panel) --------
    status_filter = request.GET.get("status", "").strip()
    payment_status_filter = request.GET.get("payment_status", "").strip()
    event_type_filter = request.GET.get("event_type", "").strip()
    state_filter = request.GET.get("state", "").strip()

    month_bookings = Booking.objects.filter(
        event_date__gte=first_of_month, event_date__lte=last_of_month,
    ).exclude(status=Booking.STATUS_CANCELLED).order_by("event_date", "id")

    if status_filter:
        month_bookings = month_bookings.filter(status=status_filter)
    if payment_status_filter and payment_status_filter in PAYMENT_STATUS_GROUPS:
        month_bookings = month_bookings.filter(status__in=PAYMENT_STATUS_GROUPS[payment_status_filter])
    if event_type_filter:
        month_bookings = month_bookings.filter(event_type=event_type_filter)
    if state_filter:
        month_bookings = month_bookings.filter(state=state_filter)

    bookings_by_date = defaultdict(list)
    for b in month_bookings:
        b.payment_status_label = _payment_status_for(b)
        b.status_color = DASHBOARD_STATUS_COLORS.get(b.status, "#666")
        bookings_by_date[b.event_date].append(b)

    # Inventory conflicts must reflect REAL reservations regardless of the
    # filters above (a filtered-out booking still holds its headsets), so
    # this is computed from a separate, unfiltered query.
    reserving_bookings = Booking.objects.filter(
        event_date__gte=first_of_month, event_date__lte=last_of_month,
        status__in=Booking.RESERVING_STATUSES,
    ).values("event_date").annotate(total=Sum("headsets"))
    reserved_by_date = {row["event_date"]: row["total"] or 0 for row in reserving_bookings}

    headset_inventory = EquipmentInventory.objects.filter(equipment_type=EQUIPMENT_HEADSET).first()
    capacity = None
    if headset_inventory:
        capacity = headset_inventory.total_quantity - headset_inventory.maintenance_quantity

    # ---- Build the 7-wide week grid (Monday first) ----------------------
    cal = calendar_module.Calendar(firstweekday=0)
    weeks = []
    for week in cal.monthdatescalendar(year, month):
        week_cells = []
        for day in week:
            reserved = reserved_by_date.get(day, 0)
            week_cells.append({
                "date": day,
                "in_month": day.month == month,
                "is_today": day == today,
                "bookings": bookings_by_date.get(day, []),
                "reserved": reserved,
                "conflict": capacity is not None and reserved > capacity,
            })
        weeks.append(week_cells)

    busy_days_count = sum(1 for bl in bookings_by_date.values() if len(bl) > 1)
    distinct_states = Booking.objects.exclude(state="").values_list("state", flat=True).distinct().order_by("state")

    # Preserve active filters across the Prev/Next/Today/jump links.
    querydict = request.GET.copy()
    querydict.pop("year", None)
    querydict.pop("month", None)
    filters_querystring = querydict.urlencode()

    context = {
        "year": year,
        "month": month,
        "month_name": calendar_module.month_name[month],
        "today": today,
        "weeks": weeks,
        "weekday_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "prev_year": prev_month_date.year,
        "prev_month": prev_month_date.month,
        "next_year": next_month_date.year,
        "next_month": next_month_date.month,
        "busy_days_count": busy_days_count,
        "month_bookings_count": sum(len(bl) for bl in bookings_by_date.values()),
        "capacity": capacity,
        "inventory_configured": headset_inventory is not None,
        "filters_querystring": filters_querystring,
        "status_filter": status_filter,
        "payment_status_filter": payment_status_filter,
        "event_type_filter": event_type_filter,
        "state_filter": state_filter,
        "status_choices": Booking.STATUS_CHOICES,
        "payment_status_choices": list(PAYMENT_STATUS_GROUPS.keys()),
        "event_type_choices": Booking.EVENT_TYPES,
        "state_choices": distinct_states,
        "year_choices": range(today.year - 1, today.year + 3),
        "month_choices": [(i, calendar_module.month_name[i]) for i in range(1, 13)],
    }
    return render(request, "booking/dashboard_calendar.html", context)


@staff_member_required
def dashboard_invoice(request, booking_id):
    """Printable, previewable invoice for a booking - reached from the
    'Print Invoice' quick action on the calendar, the dashboard table, and
    the Django admin. Pulls its numbers from documents.invoice_context()
    so this preview always matches the emailed/downloaded PDF exactly.
    Doesn't itself generate or send anything - see dashboard_generate_invoice
    / dashboard_email_invoice for the buttons that do."""
    booking_obj = get_object_or_404(Booking, pk=booking_id)
    context = documents.invoice_context(booking_obj)
    context.update({
        "payment_status_label": _payment_status_for(booking_obj),
        "status_color": DASHBOARD_STATUS_COLORS.get(booking_obj.status, "#666"),
    })
    return render(request, "booking/dashboard_invoice.html", context)


@staff_member_required
def dashboard_quotation(request, booking_id):
    """Printable, previewable quotation for a booking - the quotation
    counterpart of dashboard_invoice above. Same pattern: pulls its
    numbers from documents.quotation_context() so the preview always
    matches the emailed/downloaded PDF exactly."""
    booking_obj = get_object_or_404(Booking, pk=booking_id)
    context = documents.quotation_context(booking_obj)
    context.update({
        "payment_status_label": _payment_status_for(booking_obj),
        "status_color": DASHBOARD_STATUS_COLORS.get(booking_obj.status, "#666"),
    })
    return render(request, "booking/dashboard_quotation.html", context)


@staff_member_required
def dashboard_quotation_pdf(request, booking_id):
    """'Download Quote' quick action - generates the quotation if it
    hasn't been already (so Download always works even before the
    'Generate Quote' button has been clicked) and streams the PDF."""
    booking_obj = get_object_or_404(Booking, pk=booking_id)
    if not booking_obj.quotation_number:
        booking_obj.generate_quotation()
    pdf_bytes = documents.quotation_pdf_bytes(booking_obj)
    if pdf_bytes is None:
        messages.error(request, "Could not generate the quotation PDF - please try again.")
        return redirect("dashboard_quotation", booking_id=booking_obj.id)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="Quotation-{booking_obj.quotation_number}.pdf"'
    return response


@staff_member_required
def dashboard_invoice_pdf(request, booking_id):
    """'Download Invoice' quick action - generates the invoice if it
    hasn't been already and streams the PDF."""
    booking_obj = get_object_or_404(Booking, pk=booking_id)
    if not booking_obj.invoice_number:
        booking_obj.generate_invoice()
    pdf_bytes = documents.invoice_pdf_bytes(booking_obj)
    if pdf_bytes is None:
        messages.error(request, "Could not generate the invoice PDF - please try again.")
        return redirect("dashboard_invoice", booking_id=booking_obj.id)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="Invoice-{booking_obj.invoice_number}.pdf"'
    return response


@staff_member_required
@require_POST
def dashboard_generate_quote(request, booking_id):
    """'Generate Quote' quick action - (re)generates the quotation number/
    dates and emails it to the customer. Safe to click more than once:
    generate_quotation() keeps the existing number rather than issuing a
    new one."""
    booking_obj = get_object_or_404(Booking, pk=booking_id)
    booking_obj.generate_quotation()
    if notifications.send_quotation_email(booking_obj):
        messages.success(request, f"Quotation #{booking_obj.quotation_number} generated and emailed to {booking_obj.name}.")
    elif booking_obj.email:
        messages.error(request, f"Quotation #{booking_obj.quotation_number} was generated, but the email failed to send.")
    else:
        messages.warning(request, f"Quotation #{booking_obj.quotation_number} generated. No email on file to send it to.")
    return redirect("dashboard_quotation", booking_id=booking_obj.id)


@staff_member_required
@require_POST
def dashboard_generate_invoice(request, booking_id):
    """'Generate Invoice' quick action - (re)generates the invoice number/
    date and emails it to the customer."""
    booking_obj = get_object_or_404(Booking, pk=booking_id)
    booking_obj.generate_invoice()
    if notifications.send_invoice_email(booking_obj):
        messages.success(request, f"Invoice #{booking_obj.invoice_number} generated and emailed to {booking_obj.name}.")
    elif booking_obj.email:
        messages.error(request, f"Invoice #{booking_obj.invoice_number} was generated, but the email failed to send.")
    else:
        messages.warning(request, f"Invoice #{booking_obj.invoice_number} generated. No email on file to send it to.")
    return redirect("dashboard_invoice", booking_id=booking_obj.id)


@staff_member_required
@require_POST
def dashboard_email_quotation(request, booking_id):
    """'Email Quotation' quick action - resends the existing quotation
    (generating one first if none exists yet) without treating it as a
    fresh document."""
    booking_obj = get_object_or_404(Booking, pk=booking_id)
    if not booking_obj.quotation_number:
        booking_obj.generate_quotation()
    if notifications.send_quotation_email(booking_obj):
        messages.success(request, f"Quotation #{booking_obj.quotation_number} emailed to {booking_obj.name}.")
    elif booking_obj.email:
        messages.error(request, "Couldn't send that email - please try again or contact the customer another way.")
    else:
        messages.error(request, f"Booking #{booking_obj.id} ({booking_obj.name}) has no email on file.")
    return redirect("dashboard_quotation", booking_id=booking_obj.id)


@staff_member_required
@require_POST
def dashboard_email_invoice(request, booking_id):
    """'Email Invoice' quick action - resends the existing invoice
    (generating one first if none exists yet)."""
    booking_obj = get_object_or_404(Booking, pk=booking_id)
    if not booking_obj.invoice_number:
        booking_obj.generate_invoice()
    if notifications.send_invoice_email(booking_obj):
        messages.success(request, f"Invoice #{booking_obj.invoice_number} emailed to {booking_obj.name}.")
    elif booking_obj.email:
        messages.error(request, "Couldn't send that email - please try again or contact the customer another way.")
    else:
        messages.error(request, f"Booking #{booking_obj.id} ({booking_obj.name}) has no email on file.")
    return redirect("dashboard_invoice", booking_id=booking_obj.id)


@staff_member_required
def analytics_dashboard(request):
    """Business Analytics & Reporting dashboard: KPI cards, revenue/
    booking/payment/equipment analytics, calendar insights, and the
    report-export panel. All numbers come from analytics.py so this page
    and the analytics_data JSON endpoint (used for auto-refresh) can
    never disagree with each other."""
    payload = analytics.dashboard_json_payload()
    booking_data = analytics.booking_analytics()
    equipment_data = analytics.equipment_analytics()
    calendar_data = analytics.calendar_insights()

    distinct_states = Booking.objects.exclude(state="").values_list("state", flat=True).distinct().order_by("state")

    context = {
        "kpis": payload["kpis"],
        "revenue": payload["revenue"],
        "revenue_trend_json": json.dumps(payload["revenue_trend"]),
        "booking_trend_json": json.dumps(booking_data["trend"]),
        "booking_by_event_type_json": json.dumps(payload["booking_by_event_type"]),
        "booking_by_state_json": json.dumps(payload["booking_by_state"]),
        "peak_periods_json": json.dumps(booking_data["peak"]),
        "payments": payload["payments"],
        "equipment": equipment_data,
        "calendar": calendar_data,
        "status_choices": Booking.STATUS_CHOICES,
        "payment_status_choices": list(PAYMENT_STATUS_GROUPS.keys()),
        "event_type_choices": Booking.EVENT_TYPES,
        "state_choices": distinct_states,
        "today": timezone.localdate(),
    }
    return render(request, "booking/analytics_dashboard.html", context)


@staff_member_required
def analytics_data(request):
    """JSON endpoint the Analytics dashboard polls periodically so its
    KPI cards and charts stay current without a full page reload."""
    return JsonResponse(analytics.dashboard_json_payload())


@staff_member_required
def analytics_report(request):
    """Exports a filtered bookings report as CSV, Excel, or PDF - the
    Reports panel on the Analytics dashboard. Filters: date_from,
    date_to (event date range), status, event_type, state,
    payment_status. format=csv|xlsx|pdf (defaults to csv)."""
    bookings = reports.filter_bookings(request.GET)
    fmt = (request.GET.get("format") or "csv").strip().lower()
    if fmt == "xlsx":
        return reports.export_excel(bookings)
    if fmt == "pdf":
        filters_summary = reports.describe_filters(request.GET)
        return reports.export_pdf(bookings, filters_summary)
    return reports.export_csv(bookings)


@staff_member_required
def dashboard_report(request):
    """'Generate Report' quick action: CSV export of every booking,
    respecting whatever filters are active on the dashboard so admins can
    export exactly the slice they're looking at."""
    all_bookings = Booking.objects.order_by("-created_at")

    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    payment_status_filter = request.GET.get("payment_status", "").strip()
    event_type_filter = request.GET.get("event_type", "").strip()
    state_filter = request.GET.get("state", "").strip()
    date_filter = request.GET.get("event_date", "").strip()

    if q:
        query = Q(name__icontains=q) | Q(phone__icontains=q)
        if q.isdigit():
            query |= Q(id=int(q))
        all_bookings = all_bookings.filter(query)
    if status_filter:
        all_bookings = all_bookings.filter(status=status_filter)
    if payment_status_filter and payment_status_filter in PAYMENT_STATUS_GROUPS:
        all_bookings = all_bookings.filter(status__in=PAYMENT_STATUS_GROUPS[payment_status_filter])
    if event_type_filter:
        all_bookings = all_bookings.filter(event_type=event_type_filter)
    if state_filter:
        all_bookings = all_bookings.filter(state=state_filter)
    if date_filter:
        all_bookings = all_bookings.filter(event_date=date_filter)

    response = HttpResponse(content_type="text/csv")
    filename = f"bookings_report_{timezone.localdate().isoformat()}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        "Booking ID", "Name", "Phone", "Email", "Event Type", "Event Date", "State",
        "Guests", "Headsets", "Duration (hrs)", "Status", "Amount Paid", "Estimated Total", "Created At",
    ])
    for b in all_bookings:
        writer.writerow([
            b.id, b.name, b.phone, b.email, b.event_type, b.event_date, b.state,
            b.guests, b.headsets, b.duration, b.status, b.amount_paid,
            b.estimated_total() if b.full_price_known else "TBC", b.created_at.strftime("%Y-%m-%d %H:%M"),
        ])
    return response


@staff_member_required
def dashboard_send_email(request):
    """'Send Customer Email' quick action: pick a booking, write a subject
    and message, send it to that customer's email on file."""
    booking_obj = None
    booking_id = request.GET.get("booking_id") or request.POST.get("booking_id")
    if booking_id:
        booking_obj = Booking.objects.filter(pk=booking_id).first()

    if request.method == "POST":
        subject = request.POST.get("subject", "").strip()
        body = request.POST.get("body", "").strip()
        if not booking_obj:
            messages.error(request, "Select a booking first.")
        elif not booking_obj.email:
            messages.error(request, f"Booking #{booking_obj.id} ({booking_obj.name}) has no email on file.")
        elif not subject or not body:
            messages.error(request, "Subject and message are both required.")
        else:
            sent = notifications.send_custom_email(booking_obj, subject, body)
            if sent:
                messages.success(request, f"Email sent to {booking_obj.name} ({booking_obj.email}).")
                return redirect("admin_dashboard")
            messages.error(request, "Couldn't send that email - please try again or contact the customer another way.")

    q = request.GET.get("q", "").strip()
    results = []
    if q:
        query = Q(name__icontains=q) | Q(phone__icontains=q)
        if q.isdigit():
            query |= Q(id=int(q))
        results = Booking.objects.filter(query).order_by("-created_at")[:15]

    return render(
        request,
        "booking/dashboard_send_email.html",
        {"booking_obj": booking_obj, "q": q, "results": results},
    )


# ---------------------------------------------------------------------
# Payments (Paystack)
# ---------------------------------------------------------------------

def payment_page(request, booking_id):
    """
    Shows the Pay Full Amount button - but only if it's actually
    available for this booking's current status. No admin confirmation
    step is required first: a booking can pay from the moment it's
    created. Cancelled/Completed bookings, or a booking that's already
    fully paid, simply won't have a button (see Booking.can_pay_full).
    Deposit-only payment has been disabled - see Booking.can_pay_deposit.
    """
    booking_obj = get_object_or_404(Booking, id=booking_id)
    error = request.GET.get("error")

    context = {
        "booking": booking_obj,
        "error": error,
        "full_amount": (
            booking_obj.amount_due(Booking.PAYMENT_FULL) if booking_obj.can_pay_full else None
        ),
    }
    return render(request, "booking/payment.html", context)


@require_POST
def payment_initiate(request, booking_id):
    """
    Starts a Paystack transaction for the full amount and redirects the
    customer to Paystack's checkout. Never touches the booking's status
    or payment fields here — that only ever happens after verification.
    Deposit-only payment has been disabled - "deposit" is no longer an
    accepted payment_type here (see Booking.can_pay_deposit).
    """
    booking_obj = get_object_or_404(Booking, id=booking_id)
    payment_type = request.POST.get("payment_type")

    if payment_type != Booking.PAYMENT_FULL:
        return redirect(f"{reverse('payment_page', args=[booking_obj.id])}?error=invalid_option")

    if not booking_obj.can_pay_full:
        # Re-checked server-side regardless of what the form claims — the
        # customer's browser is never trusted for this decision.
        return redirect(f"{reverse('payment_page', args=[booking_obj.id])}?error=not_eligible")

    if not booking_obj.email:
        return redirect(f"{reverse('payment_page', args=[booking_obj.id])}?error=no_email")

    # Paying moves this booking into a RESERVING_STATUSES status
    # (Deposit Paid / Fully Paid), which actually holds the headsets for
    # its event_date. That used to only be checked when an admin manually
    # confirmed a booking - now that customers can pay straight from
    # Pending (no confirmation step first), this is the last checkpoint
    # before inventory is committed, so it has to happen here instead.
    availability_issue = booking_obj.insufficient_headset_availability()
    if availability_issue:
        logger.warning("Blocked payment for booking id=%s: %s", booking_obj.id, availability_issue)
        return redirect(f"{reverse('payment_page', args=[booking_obj.id])}?error=sold_out")

    # Quotation Workflow normally fires the moment a booking becomes
    # Confirmed. A booking can now reach payment without ever passing
    # through Confirmed, so this is the fallback trigger - guarantees a
    # quotation exists (and gets emailed) before the customer is sent to
    # Paystack, exactly like it always has for Confirmed bookings.
    if not booking_obj.quotation_number:
        booking_obj.generate_quotation()
        notifications.send_quotation_email(booking_obj)

    amount = booking_obj.amount_due(payment_type)
    reference = f"DSNG-{booking_obj.id}-{uuid.uuid4().hex[:10]}"

    PaymentTransaction.objects.create(
        booking=booking_obj,
        reference=reference,
        payment_type=payment_type,
        amount=amount,
        status=PaymentTransaction.STATUS_PENDING,
    )

    callback_url = request.build_absolute_uri(reverse("payment_callback"))
    try:
        checkout_url = paystack.initialize_transaction(
            email=booking_obj.email,
            amount_naira=amount,
            reference=reference,
            callback_url=callback_url,
            metadata={"booking_id": booking_obj.id, "payment_type": payment_type},
        )
    except paystack.PaystackError:
        logger.exception("Paystack initialize failed for booking id=%s", booking_obj.id)
        return redirect(f"{reverse('payment_page', args=[booking_obj.id])}?error=init_failed")

    return redirect(checkout_url)


def payment_callback(request):
    """
    Where Paystack redirects the customer's browser back to after checkout.
    This is a convenience for the customer (immediate feedback) — it is
    NOT trusted as proof of payment on its own. The actual verification
    happens in _verify_and_process_payment, which calls Paystack's
    verify API using our secret key, regardless of what's in the URL.
    """
    reference = request.GET.get("reference")
    if not reference:
        return HttpResponseBadRequest("Missing reference")

    success, booking_obj, message = _verify_and_process_payment(reference)

    if not booking_obj:
        return HttpResponseBadRequest("Unknown payment reference")

    if success:
        return redirect("payment_success", booking_id=booking_obj.id)

    return redirect(f"{reverse('payment_page', args=[booking_obj.id])}?error=verify_failed")


def payment_success(request, booking_id):
    booking_obj = get_object_or_404(Booking, id=booking_id)
    latest = booking_obj.payment_transactions.filter(
        status=PaymentTransaction.STATUS_SUCCESS
    ).first()
    return render(request, "booking/payment_success.html", {"booking": booking_obj, "transaction": latest})


@csrf_exempt
@require_POST
def payment_webhook(request):
    """
    Paystack's server-to-server webhook — the reliable path, since it
    fires even if the customer closes their browser before the callback
    redirect completes. Every request is signature-verified before we
    trust anything in the body (see paystack.verify_webhook_signature).
    """
    signature = request.headers.get("x-paystack-signature", "")
    if not paystack.verify_webhook_signature(request.body, signature):
        logger.warning("Rejected webhook with invalid Paystack signature")
        return HttpResponse(status=401)

    try:
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("Invalid JSON")

    if payload.get("event") != "charge.success":
        # Ignore every other event type - we only care about successful
        # charges landing here; verify_transaction is the source of truth
        # for the actual outcome either way.
        return HttpResponse(status=200)

    reference = payload.get("data", {}).get("reference")
    if not reference:
        return HttpResponseBadRequest("Missing reference")

    _verify_and_process_payment(reference)
    return HttpResponse(status=200)


def _verify_and_process_payment(reference):
    """
    Shared by both the callback and the webhook so a payment is processed
    exactly once no matter which path (or both, in either order) actually
    triggers it. Always re-verifies against Paystack's API directly -
    never trusts the caller's claim that payment succeeded.

    Returns (success: bool, booking: Booking | None, message: str).
    """
    try:
        transaction = PaymentTransaction.objects.select_related("booking").get(reference=reference)
    except PaymentTransaction.DoesNotExist:
        logger.error("Verification requested for unknown reference: %s", reference)
        return False, None, "Unknown payment reference"

    booking_obj = transaction.booking

    if transaction.status == PaymentTransaction.STATUS_SUCCESS:
        # Already processed (e.g. both the callback AND the webhook fired
        # for the same payment) - don't re-apply it or double-send emails.
        return True, booking_obj, "Already processed"

    try:
        data = paystack.verify_transaction(reference)
    except paystack.PaystackError as exc:
        transaction.status = PaymentTransaction.STATUS_FAILED
        transaction.gateway_response = str(exc)
        transaction.save()
        logger.error("Payment verification failed for %s: %s", reference, exc)
        return False, booking_obj, "Could not verify payment"

    expected_kobo = transaction.amount * 100
    verified_ok = data.get("status") == "success" and data.get("amount") == expected_kobo

    if not verified_ok:
        transaction.status = PaymentTransaction.STATUS_FAILED
        transaction.gateway_response = str(data)
        transaction.save()
        logger.error(
            "Payment verification mismatch for %s: expected %s kobo, got status=%s amount=%s",
            reference, expected_kobo, data.get("status"), data.get("amount"),
        )
        return False, booking_obj, "Payment not verified"

    # Verified. Apply it.
    transaction.status = PaymentTransaction.STATUS_SUCCESS
    transaction.gateway_response = str(data)
    transaction.verified_at = timezone.now()
    transaction.save()

    booking_obj.record_verified_payment(
        reference=reference,
        amount=transaction.amount,
        method="Paystack",
        payment_type=transaction.payment_type,
        paid_at=timezone.now(),
    )

    notifications.send_payment_receipt(booking_obj, transaction)
    notifications.send_payment_notification_business(booking_obj, transaction)
    # Invoice Workflow: Payment Successful -> Invoice Generated -> Email
    # Invoice. record_verified_payment() above already generated/refreshed
    # the invoice's fields (booking_obj.invoice_number etc.) - this is the
    # "Email Invoice" step. Best-effort like the receipt emails above: a
    # failed send here must never make payment verification itself fail.
    notifications.send_invoice_email(booking_obj)

    return True, booking_obj, "Payment verified"
