"""
Small shared constants/helpers used by views.py, analytics.py, and
reports.py. Split out from views.py so the analytics/report modules never
have to import views.py (which would create a circular import, since
views.py itself imports analytics and reports).
"""
from .models import Booking

# Colors for the status pills on the dashboards.
DASHBOARD_STATUS_COLORS = {
    Booking.STATUS_PENDING: "#b8860b",
    Booking.STATUS_CONFIRMED: "#1a7f37",
    Booking.STATUS_DEPOSIT_PAID: "#9a6700",
    Booking.STATUS_FULLY_PAID: "#0969da",
    Booking.STATUS_COMPLETED: "#1f6feb",
    Booking.STATUS_CANCELLED: "#cf222e",
}

# Booking statuses grouped into a simpler "payment status" for dashboard
# filters/badges and for the Payment Analytics panel. There's no
# dedicated payment-status field on the model - it's always derived from
# booking status.
PAYMENT_STATUS_GROUPS = {
    "Unpaid": [Booking.STATUS_PENDING, Booking.STATUS_CONFIRMED],
    "Deposit Paid": [Booking.STATUS_DEPOSIT_PAID],
    "Fully Paid": [Booking.STATUS_FULLY_PAID, Booking.STATUS_COMPLETED],
    "Cancelled": [Booking.STATUS_CANCELLED],
}


def payment_status_for(booking):
    """Inverse of PAYMENT_STATUS_GROUPS - the label for one booking."""
    for label, statuses in PAYMENT_STATUS_GROUPS.items():
        if booking.status in statuses:
            return label
    return "Unpaid"
