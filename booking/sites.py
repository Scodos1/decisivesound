"""Custom Django AdminSite for Decisive Sound NG.

Replaces the stock A-Z app/model listing with business sections
(Bookings & payments first, Team & access last) so staff see the
most-used models at the top. Wired up in decisivesounds/urls.py.
"""
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group, User
from django.utils import timezone

from . import analytics
from .models import Booking, CancellationRequest


# Booking status pill colours — shared with booking/admin.py's badges
# so the dashboard and the changelists never drift apart.
STATUS_COLORS = {
    Booking.STATUS_PENDING: "#b8860b",
    Booking.STATUS_CONFIRMED: "#1a7f37",
    Booking.STATUS_DEPOSIT_PAID: "#9a6700",
    Booking.STATUS_FULLY_PAID: "#0969da",
    Booking.STATUS_COMPLETED: "#1f6feb",
    Booking.STATUS_CANCELLED: "#cf222e",
}


# Section order on the admin index. Models not listed here fall through
# to a section named after their own app, below these.
SECTIONS = [
    ("Bookings & payments", ("Booking", "CancellationRequest", "PaymentTransaction")),
    ("Equipment", ("EquipmentInventory", "EquipmentMaintenanceLog")),
    ("Gallery & content", ("GalleryImage",)),
    ("Customers", ("CustomerProfile", "Notification")),
    ("Team & access", ("User", "Group")),
]

# One-line helper shown under each model on the admin index
# (templates/admin/index.html). Keep these short.
MODEL_BLURBS = {
    "Booking": "Quotes, payments & event dates",
    "CancellationRequest": "Approve or reject portal requests",
    "PaymentTransaction": "Paystack + manual payment log",
    "EquipmentInventory": "Headset stock & availability",
    "EquipmentMaintenanceLog": "Repairs & faulty units",
    "GalleryImage": "Photos & videos on the public site",
    "CustomerProfile": "Customer portal accounts",
    "Notification": "Customer portal message feed",
    "User": "Staff logins",
    "Group": "Permission groups",
}


# Material Symbols icon per section + model (templates/admin/index.html).
SECTION_ICONS = {
    "Bookings & payments": "payments",
    "Equipment": "headphones",
    "Gallery & content": "photo_library",
    "Customers": "group",
    "Team & access": "shield_person",
}

MODEL_ICONS = {
    "Booking": "calendar_month",
    "CancellationRequest": "event_busy",
    "PaymentTransaction": "receipt_long",
    "EquipmentInventory": "headphones",
    "EquipmentMaintenanceLog": "build",
    "GalleryImage": "photo_library",
    "CustomerProfile": "person",
    "Notification": "notifications",
    "User": "badge",
    "Group": "key",
}


class DecisiveAdminSite(admin.AdminSite):
    site_header = "Decisive Sound NG — Administration"
    site_title = "Decisive Sound NG Admin"
    index_title = "Bookings, Equipment & Gallery"

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        order = {name: i for i, (name, _members) in enumerate(SECTIONS)}
        member_to_section = {m: s for s, members in SECTIONS for m in members}
        member_index = {m: i for _, members in SECTIONS for i, m in enumerate(members)}
        for app in app_list:
            for model in app["models"]:
                model["section"] = member_to_section.get(model["object_name"], app["name"])
                model["section_order"] = order.get(model["section"], len(SECTIONS))
                model["blurb"] = MODEL_BLURBS.get(model["object_name"], "")
                model["icon"] = MODEL_ICONS.get(model["object_name"], "widgets")
                model["section_icon"] = SECTION_ICONS.get(model["section"], "widgets")
            app["models"].sort(
                key=lambda m: (
                    m["section_order"],
                    member_index.get(m["object_name"], 0),
                    m["name"].lower(),
                )
            )
        # Booking app first, auth last (the only two apps today).
        app_list.sort(key=lambda a: 0 if a["app_label"] == "booking" else 1)
        return app_list

    def index(self, request, extra_context=None):
        """Stock admin index plus dashboard numbers — KPIs come from
        booking/analytics.py (same functions as the staff Analytics
        page) so the two can never disagree."""
        today = timezone.localdate()
        hour = timezone.localtime().hour
        greeting = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"

        active_statuses = (
            Booking.STATUS_CONFIRMED,
            Booking.STATUS_DEPOSIT_PAID,
            Booking.STATUS_FULLY_PAID,
        )
        pending = list(
            Booking.objects.filter(status=Booking.STATUS_PENDING).order_by("event_date")[:6]
        )
        upcoming = list(
            Booking.objects.filter(event_date__gte=today, status__in=active_statuses)
            .order_by("event_date")[:6]
        )
        cancellations = list(
            CancellationRequest.objects.filter(status=CancellationRequest.STATUS_PENDING)
            .select_related("booking", "requested_by")[:6]
        )
        for booking in pending + upcoming:
            booking.status_color = STATUS_COLORS.get(booking.status, "#666")

        extra = {
            "greeting": greeting,
            "dashboard_kpis": analytics.kpis(),
            "dashboard_revenue_month": analytics.revenue_summary()["this_month"],
            "dashboard_pending": pending,
            "dashboard_upcoming": upcoming,
            "dashboard_cancellations": cancellations,
        }
        extra_context = {**(extra_context or {}), **extra}
        return super().index(request, extra_context=extra_context)


decisive_site = DecisiveAdminSite(name="admin")

# Auth models live on the default site normally — re-register them here
# (with Django's own ModelAdmins) so Team & access still appears.
decisive_site.register(User, UserAdmin)
decisive_site.register(Group, GroupAdmin)
