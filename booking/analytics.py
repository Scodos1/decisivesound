"""
Analytics & Reporting - the data-computation layer behind the Analytics
dashboard (views.analytics_dashboard / views.analytics_data) and the
exportable reports (reports.py). Kept separate from views.py so the
full-page render and the JSON auto-refresh endpoint can never drift out
of sync - both call the exact same functions below.

Nothing here writes to the database - every function is a read-only
aggregation over Booking / PaymentTransaction / EquipmentInventory /
EquipmentMaintenanceLog.
"""
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from .models import (
    Booking,
    EQUIPMENT_HEADSET,
    EquipmentInventory,
    EquipmentMaintenanceLog,
    PaymentTransaction,
)

# How many months of history the revenue/booking trend line charts show.
TREND_MONTHS = 12

# How far ahead "busy dates" / "inventory conflict" calendar insights look.
UPCOMING_WINDOW_DAYS = 90

WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _shift_month(d, delta):
    """First-of-month date `delta` months away from d (delta may be negative)."""
    month_index = d.month - 1 + delta
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return d.replace(year=year, month=month, day=1)


def _month_buckets(months=TREND_MONTHS):
    """List of first-of-month dates, oldest first, ending at the current month."""
    today = timezone.localdate()
    buckets = []
    cursor = today.replace(day=1)
    for _ in range(months):
        buckets.append(cursor)
        cursor = _shift_month(cursor, -1)
    buckets.reverse()
    return buckets


# ---------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------

def outstanding_payments(bookings=None):
    """Total remaining balance across active bookings where the full
    price is actually a known number (see Booking.full_price_known) -
    shared by the KPI cards here and the original admin_dashboard view."""
    bookings = bookings if bookings is not None else Booking.objects.all()
    return sum(
        b.estimated_total() - b.amount_paid
        for b in bookings.exclude(
            status__in=[Booking.STATUS_CANCELLED, Booking.STATUS_FULLY_PAID, Booking.STATUS_COMPLETED]
        )
        if b.full_price_known
    )


def kpis():
    bookings = Booking.objects.all()
    counts = dict(
        bookings.values("status").annotate(c=Count("id")).values_list("status", "c")
    )
    total_revenue = PaymentTransaction.objects.filter(
        status=PaymentTransaction.STATUS_SUCCESS
    ).aggregate(t=Sum("amount"))["t"] or 0

    headset_inventory = EquipmentInventory.objects.filter(equipment_type=EQUIPMENT_HEADSET).first()
    available_headsets = headset_inventory.available_today() if headset_inventory else 0
    reserved_headsets = headset_inventory.reserved_today() if headset_inventory else 0

    return {
        "total_bookings": bookings.count(),
        "confirmed_bookings": counts.get(Booking.STATUS_CONFIRMED, 0),
        "pending_bookings": counts.get(Booking.STATUS_PENDING, 0),
        "completed_events": counts.get(Booking.STATUS_COMPLETED, 0),
        "cancelled_bookings": counts.get(Booking.STATUS_CANCELLED, 0),
        "total_revenue": total_revenue,
        "outstanding_payments": outstanding_payments(bookings),
        "available_headsets": available_headsets,
        "reserved_headsets": reserved_headsets,
    }


# ---------------------------------------------------------------------
# Revenue analytics
# ---------------------------------------------------------------------

def revenue_summary():
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    successful = PaymentTransaction.objects.filter(status=PaymentTransaction.STATUS_SUCCESS)

    def total_since(start_date):
        return successful.filter(verified_at__date__gte=start_date).aggregate(t=Sum("amount"))["t"] or 0

    return {
        "today": total_since(today),
        "this_week": total_since(week_start),
        "this_month": total_since(month_start),
        "this_year": total_since(year_start),
    }


def revenue_trend(months=TREND_MONTHS):
    """Monthly revenue (verified payments) for the last `months` months,
    oldest first - feeds the Revenue Analytics line chart."""
    buckets = _month_buckets(months)
    earliest = buckets[0]
    rows = (
        PaymentTransaction.objects.filter(
            status=PaymentTransaction.STATUS_SUCCESS, verified_at__date__gte=earliest,
        )
        .values("verified_at__year", "verified_at__month")
        .annotate(total=Sum("amount"))
    )
    totals = {(r["verified_at__year"], r["verified_at__month"]): r["total"] for r in rows}
    labels, values = [], []
    for key in buckets:
        labels.append(key.strftime("%b %Y"))
        values.append(totals.get((key.year, key.month), 0))
    return {"labels": labels, "values": values}


# ---------------------------------------------------------------------
# Booking analytics
# ---------------------------------------------------------------------

def booking_trend(months=TREND_MONTHS):
    """Bookings created per month for the last `months` months, oldest
    first - feeds the Booking Trends by Month chart."""
    buckets = _month_buckets(months)
    earliest = buckets[0]
    rows = (
        Booking.objects.filter(created_at__date__gte=earliest)
        .values("created_at__year", "created_at__month")
        .annotate(count=Count("id"))
    )
    totals = {(r["created_at__year"], r["created_at__month"]): r["count"] for r in rows}
    labels, values = [], []
    for key in buckets:
        labels.append(key.strftime("%b %Y"))
        values.append(totals.get((key.year, key.month), 0))
    return {"labels": labels, "values": values}


def peak_booking_periods():
    """Which day-of-week has the most event dates booked (all-time,
    active bookings only) - helps staff anticipate demand."""
    active_dates = Booking.objects.exclude(status=Booking.STATUS_CANCELLED).values_list(
        "event_date", flat=True
    )
    counts = [0] * 7
    for event_date in active_dates:
        counts[event_date.weekday()] += 1
    return {"labels": WEEKDAY_LABELS, "values": counts}


def booking_analytics():
    active = Booking.objects.exclude(status=Booking.STATUS_CANCELLED)
    by_event_type = list(
        active.values("event_type").annotate(count=Count("id")).order_by("-count")
    )
    by_state = list(
        active.exclude(state="").values("state").annotate(count=Count("id")).order_by("-count")[:10]
    )
    return {
        "by_event_type": by_event_type,
        "by_state": by_state,
        "trend": booking_trend(),
        "peak": peak_booking_periods(),
    }


# ---------------------------------------------------------------------
# Payment analytics
# ---------------------------------------------------------------------

def payment_analytics():
    counts = dict(
        Booking.objects.values("status").annotate(c=Count("id")).values_list("status", "c")
    )
    fully_paid = counts.get(Booking.STATUS_FULLY_PAID, 0) + counts.get(Booking.STATUS_COMPLETED, 0)
    partially_paid = counts.get(Booking.STATUS_DEPOSIT_PAID, 0)
    pending_payment = counts.get(Booking.STATUS_PENDING, 0) + counts.get(Booking.STATUS_CONFIRMED, 0)
    failed_payments = PaymentTransaction.objects.filter(status=PaymentTransaction.STATUS_FAILED).count()
    return {
        "fully_paid": fully_paid,
        "partially_paid": partially_paid,
        "pending_payment": pending_payment,
        "failed_payments": failed_payments,
    }


# ---------------------------------------------------------------------
# Equipment analytics
# ---------------------------------------------------------------------

def equipment_analytics():
    today = timezone.localdate()

    inventory_rows = []
    for inv in EquipmentInventory.objects.all():
        inventory_rows.append({
            "name": inv.name,
            "type": inv.equipment_type,
            "total": inv.total_quantity,
            "maintenance": inv.maintenance_quantity,
            "reserved_today": inv.reserved_on(today),
            "available_today": inv.available_on(today),
        })
    most_frequently_rented = sorted(inventory_rows, key=lambda r: r["reserved_today"], reverse=True)

    # Utilization rate for headsets this month (the only equipment type
    # tied to bookings - see EquipmentInventory's docstring). Headset-days
    # booked so far this month, divided by headset-days available.
    headset_inventory = EquipmentInventory.objects.filter(equipment_type=EQUIPMENT_HEADSET).first()
    utilization_rate = None
    if headset_inventory:
        capacity = headset_inventory.total_quantity - headset_inventory.maintenance_quantity
        if capacity > 0:
            month_start = today.replace(day=1)
            booked_headset_days = 0
            d = month_start
            while d <= today:
                booked_headset_days += headset_inventory.reserved_on(d)
                d += timedelta(days=1)
            possible_headset_days = capacity * today.day
            if possible_headset_days:
                utilization_rate = round((booked_headset_days / possible_headset_days) * 100, 1)

    maintenance_history = list(
        EquipmentMaintenanceLog.objects.select_related("equipment").order_by("-started_at")[:15]
    )

    return {
        "inventory": inventory_rows,
        "utilization_rate": utilization_rate,
        "most_frequently_rented": most_frequently_rented,
        "maintenance_history": maintenance_history,
    }


# ---------------------------------------------------------------------
# Calendar insights
# ---------------------------------------------------------------------

def calendar_insights():
    today = timezone.localdate()
    week_end = today + timedelta(days=7)
    horizon = today + timedelta(days=UPCOMING_WINDOW_DAYS)
    active = Booking.objects.exclude(status=Booking.STATUS_CANCELLED)

    todays_events = active.filter(event_date=today).count()
    upcoming_this_week = active.filter(event_date__gt=today, event_date__lte=week_end).count()

    counts_by_date = (
        active.filter(event_date__gte=today, event_date__lte=horizon)
        .values("event_date").annotate(count=Count("id")).order_by("event_date")
    )
    busy_dates = [row["event_date"] for row in counts_by_date if row["count"] > 1]

    reserving = (
        Booking.objects.filter(
            event_date__gte=today, event_date__lte=horizon, status__in=Booking.RESERVING_STATUSES,
        ).values("event_date").annotate(total=Sum("headsets")).order_by("event_date")
    )
    headset_inventory = EquipmentInventory.objects.filter(equipment_type=EQUIPMENT_HEADSET).first()
    capacity = (
        headset_inventory.total_quantity - headset_inventory.maintenance_quantity
        if headset_inventory else None
    )
    conflict_dates = []
    if capacity is not None:
        conflict_dates = [row["event_date"] for row in reserving if (row["total"] or 0) > capacity]

    return {
        "todays_events": todays_events,
        "upcoming_this_week": upcoming_this_week,
        "busy_dates": busy_dates,
        "conflict_dates": conflict_dates,
    }


# ---------------------------------------------------------------------
# JSON payload shared by the initial page render and the auto-refresh
# polling endpoint (views.analytics_data) - see analytics_dashboard.html.
# ---------------------------------------------------------------------

def dashboard_json_payload():
    b = booking_analytics()
    c = calendar_insights()
    return {
        "kpis": kpis(),
        "revenue": revenue_summary(),
        "revenue_trend": revenue_trend(),
        "booking_trend": b["trend"],
        "booking_by_event_type": {
            "labels": [row["event_type"] for row in b["by_event_type"]],
            "values": [row["count"] for row in b["by_event_type"]],
        },
        "booking_by_state": {
            "labels": [row["state"] for row in b["by_state"]],
            "values": [row["count"] for row in b["by_state"]],
        },
        "peak_periods": b["peak"],
        "payments": payment_analytics(),
        "equipment_utilization_rate": equipment_analytics()["utilization_rate"],
        "calendar": {
            "todays_events": c["todays_events"],
            "upcoming_this_week": c["upcoming_this_week"],
            "busy_dates_count": len(c["busy_dates"]),
            "conflict_dates_count": len(c["conflict_dates"]),
        },
        "generated_at": timezone.now().isoformat(),
    }
