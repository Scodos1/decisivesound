from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from . import notifications
from .models import (
    Booking,
    CancellationRequest,
    CustomerProfile,
    EquipmentInventory,
    EquipmentMaintenanceLog,
    GalleryImage,
    Notification,
    PaymentTransaction,
)

STATUS_COLORS = {
    Booking.STATUS_PENDING: "#b8860b",
    Booking.STATUS_CONFIRMED: "#1a7f37",
    Booking.STATUS_DEPOSIT_PAID: "#9a6700",
    Booking.STATUS_FULLY_PAID: "#0969da",
    Booking.STATUS_COMPLETED: "#1f6feb",
    Booking.STATUS_CANCELLED: "#cf222e",
}

PAYMENT_TX_STATUS_COLORS = {
    PaymentTransaction.STATUS_PENDING: "#b8860b",
    PaymentTransaction.STATUS_SUCCESS: "#1a7f37",
    PaymentTransaction.STATUS_FAILED: "#cf222e",
}


class PaymentTransactionInline(admin.TabularInline):
    """Read-only log of every payment attempt on this booking, successful
    or not - visible from the booking detail page per the spec. Only the
    payment flow itself (booking/views.py) should ever create/edit these,
    so no add/change/delete permissions here."""
    model = PaymentTransaction
    extra = 0
    fields = ("reference", "payment_type", "amount", "status", "created_at", "verified_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    change_list_template = "admin/booking/booking/change_list.html"

    # "Customer  Event  Date  Status" — status is always visible in the list.
    list_display = (
        "name", "event_type", "event_date", "state",
        "headsets", "status_badge", "created_at",
    )
    # Filter by status (or any other column) ...
    list_filter = ("status", "event_type", "state", "event_date")
    # ... and search works independently of whatever filter is active, so a
    # search always covers bookings in every status.
    search_fields = ("name", "phone", "email", "address")
    ordering = ("-created_at",)
    actions = [
        "mark_pending", "mark_confirmed", "mark_deposit_paid",
        "mark_fully_paid", "mark_completed", "mark_cancelled",
    ]
    inlines = [PaymentTransactionInline]

    readonly_fields = (
        "payment_reference", "amount_paid", "payment_date", "payment_method",
        "outstanding_balance", "payment_link",
        "quotation_number", "quotation_generated_at", "quotation_expiry_date",
        "quotation_status", "quotation_link",
        "invoice_number", "invoice_generated_at", "invoice_status", "invoice_link",
    )

    fieldsets = (
        (None, {
            "fields": (
                "name", "phone", "email", "event_type", "event_date",
                "state", "address", "guests", "headsets", "duration", "message",
            ),
        }),
        ("Booking status", {
            "fields": ("status",),
            "description": "Only staff can change this — customers never see or set it.",
        }),
        ("Payment", {
            "fields": (
                "payment_reference", "amount_paid", "payment_date",
                "payment_method", "outstanding_balance", "payment_link",
            ),
            "description": (
                "These fields are system-managed — they only ever update "
                "automatically after a verified Paystack payment. Use "
                "\"Payment link\" below to send the customer a link to pay "
                "online once the booking is Confirmed."
            ),
        }),
        ("Quotation", {
            "fields": (
                "quotation_number", "quotation_generated_at",
                "quotation_expiry_date", "quotation_status", "quotation_link",
            ),
            "description": (
                "Generated automatically the moment a booking becomes "
                "Confirmed and emailed to the customer. Use \"Quotation "
                "link\" below to preview it, regenerate it, download the "
                "PDF, or re-send the email."
            ),
        }),
        ("Invoice", {
            "fields": (
                "invoice_number", "invoice_generated_at",
                "invoice_status", "invoice_link",
            ),
            "description": (
                "Generated automatically after every verified payment and "
                "emailed to the customer. Use \"Invoice link\" below to "
                "preview it, regenerate it, download the PDF, or re-send "
                "the email."
            ),
        }),
    )

    def status_badge(self, obj):
        color = STATUS_COLORS.get(obj.status, "#666")
        return format_html(
            '<span style="padding:3px 10px;border-radius:999px;font-size:12px;'
            'font-weight:600;color:#fff;background:{};white-space:nowrap;">{}</span>',
            color, obj.status,
        )
    status_badge.short_description = "Status"
    status_badge.admin_order_field = "status"

    def outstanding_balance(self, obj):
        if not obj.full_price_known:
            return "Unknown — final price not yet confirmed for this state"
        remaining = obj.estimated_total() - obj.amount_paid
        return f"₦{max(remaining, 0):,}"
    outstanding_balance.short_description = "Outstanding balance"

    def payment_link(self, obj):
        if obj.pk is None:
            return "— save the booking first —"
        if not obj.can_pay:
            return "Not available (booking must be Confirmed, and not already fully paid)"
        url = reverse("payment_page", args=[obj.pk])
        return format_html('<a href="{0}" target="_blank">{0}</a>', url)
    payment_link.short_description = "Payment link (send to customer)"

    def quotation_link(self, obj):
        if obj.pk is None:
            return "— save the booking first —"
        url = reverse("dashboard_quotation", args=[obj.pk])
        return format_html('<a href="{0}" target="_blank">Preview / generate / download / email →</a>', url)
    quotation_link.short_description = "Quotation"

    def invoice_link(self, obj):
        if obj.pk is None:
            return "— save the booking first —"
        url = reverse("dashboard_invoice", args=[obj.pk])
        return format_html('<a href="{0}" target="_blank">Preview / generate / download / email →</a>', url)
    invoice_link.short_description = "Invoice"

    @admin.action(description="Mark selected bookings as Pending")
    def mark_pending(self, request, queryset):
        self._bulk_set_status(request, queryset, Booking.STATUS_PENDING)

    @admin.action(description="Mark selected bookings as Confirmed")
    def mark_confirmed(self, request, queryset):
        self._bulk_set_status(request, queryset, Booking.STATUS_CONFIRMED)

    @admin.action(description="Mark selected bookings as Deposit Paid")
    def mark_deposit_paid(self, request, queryset):
        self._bulk_set_status(request, queryset, Booking.STATUS_DEPOSIT_PAID)

    @admin.action(description="Mark selected bookings as Fully Paid")
    def mark_fully_paid(self, request, queryset):
        self._bulk_set_status(request, queryset, Booking.STATUS_FULLY_PAID)

    @admin.action(description="Mark selected bookings as Completed")
    def mark_completed(self, request, queryset):
        self._bulk_set_status(request, queryset, Booking.STATUS_COMPLETED)

    @admin.action(description="Mark selected bookings as Cancelled")
    def mark_cancelled(self, request, queryset):
        self._bulk_set_status(request, queryset, Booking.STATUS_CANCELLED)

    def _bulk_set_status(self, request, queryset, new_status):
        # Deliberately NOT queryset.update(status=...): that bypasses
        # Model.save() entirely (by Django design), which would silently
        # skip the status-change notification emails in notifications.py.
        # Looping is slightly less efficient but keeps bulk actions and
        # single-record edits behaving identically.
        #
        # Bulk actions also bypass ModelForm validation (Booking.clean()
        # only runs through the single-record admin change form), so the
        # headset-inventory check has to be done explicitly here too.
        blocked = []
        updated = 0
        for obj in queryset:
            if new_status in Booking.RESERVING_STATUSES:
                obj.status = new_status
                reason = obj.insufficient_headset_availability()
                if reason:
                    blocked.append(f"#{obj.id} {obj.name}: {reason}")
                    continue
            obj.status = new_status
            obj.save()
            updated += 1

        if updated:
            self.message_user(request, f"Updated {updated} booking(s) to {new_status}.")
        if blocked:
            self.message_user(
                request,
                f"{len(blocked)} booking(s) could NOT be set to {new_status} - "
                f"insufficient headset inventory: " + "; ".join(blocked),
                level=messages.WARNING,
            )

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    """
    Standalone view of every payment attempt across all bookings — this is
    where failed/unverified attempts are reviewable, per the spec's error
    handling requirement ("log the failed verification for administrative
    review"). System-managed: nothing here should be manually created or
    edited, only viewed.
    """
    list_display = ("reference", "booking_link", "payment_type", "amount", "status_badge", "created_at", "verified_at")
    list_filter = ("status", "payment_type")
    search_fields = ("reference", "booking__name", "booking__phone", "booking__email")
    ordering = ("-created_at",)
    readonly_fields = ("booking", "reference", "payment_type", "amount", "status", "gateway_response", "created_at", "verified_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def booking_link(self, obj):
        url = reverse("admin:booking_booking_change", args=[obj.booking_id])
        return format_html('<a href="{}">{}</a>', url, obj.booking)
    booking_link.short_description = "Booking"

    def status_badge(self, obj):
        color = PAYMENT_TX_STATUS_COLORS.get(obj.status, "#666")
        return format_html(
            '<span style="padding:3px 10px;border-radius:999px;font-size:12px;'
            'font-weight:600;color:#fff;background:{};white-space:nowrap;">{}</span>',
            color, obj.status,
        )
    status_badge.short_description = "Status"
    status_badge.admin_order_field = "status"


@admin.register(EquipmentInventory)
class EquipmentInventoryAdmin(admin.ModelAdmin):
    """
    Add equipment types, edit total/maintenance quantities, and see
    today's reserved/available at a glance. Reserved/Available aren't
    editable fields - they're always computed live from bookings for the
    current date (see EquipmentInventory.reserved_on/available_on), so
    they can never drift out of sync.
    """
    list_display = (
        "name", "equipment_type", "total_quantity",
        "reserved_today_display", "available_today_display",
        "maintenance_quantity", "last_updated",
    )
    readonly_fields = ("last_updated",)
    fields = ("name", "equipment_type", "total_quantity", "maintenance_quantity", "last_updated")

    def reserved_today_display(self, obj):
        return obj.reserved_today()
    reserved_today_display.short_description = "Reserved (today)"

    def available_today_display(self, obj):
        return obj.available_today()
    available_today_display.short_description = "Available (today)"


@admin.register(EquipmentMaintenanceLog)
class EquipmentMaintenanceLogAdmin(admin.ModelAdmin):
    """Log entries feeding the Analytics dashboard's Maintenance History
    panel. See EquipmentMaintenanceLog's docstring - this is a log only;
    it doesn't itself adjust EquipmentInventory.maintenance_quantity."""
    list_display = ("equipment", "quantity", "started_at", "resolved_at", "status_display", "reason")
    list_filter = ("equipment", "resolved_at")
    search_fields = ("reason", "notes")
    ordering = ("-started_at",)

    def status_display(self, obj):
        if obj.is_ongoing:
            return format_html('<span style="color:#b8860b;font-weight:600;">Ongoing</span>')
        return format_html('<span style="color:#1a7f37;font-weight:600;">Resolved</span>')
    status_display.short_description = "Status"


# ---------------------------------------------------------------------
# Customer Portal
# ---------------------------------------------------------------------

@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "email_verified", "created_at")
    search_fields = ("user__username", "user__email", "user__first_name", "phone")
    list_filter = ("email_verified",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "notif_type", "message", "booking", "is_read", "created_at")
    list_filter = ("notif_type", "is_read")
    search_fields = ("user__username", "user__email", "message")
    autocomplete_fields = ["booking"]


@admin.register(CancellationRequest)
class CancellationRequestAdmin(admin.ModelAdmin):
    """
    Where staff review customer-submitted cancellation requests (Customer
    Portal > booking detail > Request Cancellation). Approving here is
    the ONLY thing that actually cancels the booking - see the actions
    below - a pending request by itself never changes booking.status.
    """
    list_display = ("booking", "requested_by", "status_display", "requested_at", "resolved_at")
    list_filter = ("status",)
    search_fields = ("booking__name", "booking__phone", "requested_by__username", "requested_by__email")
    autocomplete_fields = ["booking", "requested_by"]
    actions = ["approve_requests", "reject_requests"]

    def status_display(self, obj):
        color = {"Pending": "#b8860b", "Approved": "#1a7f37", "Rejected": "#cf222e"}.get(obj.status, "#666")
        return format_html('<span style="color:{};font-weight:600;">{}</span>', color, obj.status)
    status_display.short_description = "Status"

    def approve_requests(self, request, queryset):
        approved = 0
        for cancellation_request in queryset.filter(status=CancellationRequest.STATUS_PENDING):
            cancellation_request.status = CancellationRequest.STATUS_APPROVED
            cancellation_request.resolved_at = timezone.now()
            cancellation_request.save()
            cancellation_request.booking.status = Booking.STATUS_CANCELLED
            cancellation_request.booking.save()  # fires the existing "booking cancelled" email via Booking.save()
            notifications.send_cancellation_decision(cancellation_request)
            approved += 1
        self.message_user(request, f"Approved {approved} cancellation request(s) and cancelled the matching booking(s).", messages.SUCCESS)
    approve_requests.short_description = "Approve selected requests (cancels the booking)"

    def reject_requests(self, request, queryset):
        rejected = 0
        for cancellation_request in queryset.filter(status=CancellationRequest.STATUS_PENDING):
            cancellation_request.status = CancellationRequest.STATUS_REJECTED
            cancellation_request.resolved_at = timezone.now()
            cancellation_request.save()
            notifications.send_cancellation_decision(cancellation_request)
            rejected += 1
        self.message_user(request, f"Rejected {rejected} cancellation request(s). The booking(s) were left unchanged.", messages.SUCCESS)
    reject_requests.short_description = "Reject selected requests (booking is left unchanged)"


# ---------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------

@admin.register(GalleryImage)
class GalleryImageAdmin(admin.ModelAdmin):
    """
    Where staff add/remove/reorder photos and video clips on the public
    Gallery page (templates/booking/gallery.html) - no code changes needed
    to update the gallery, just upload here. No category/tag needed: pick
    Photo or Video, upload the file, optionally add a caption, and it
    appears on the site.
    """
    list_display = ("thumbnail", "display_caption", "media_type", "display_order", "is_active", "uploaded_at")
    list_display_links = ("thumbnail", "display_caption")
    list_editable = ("display_order", "is_active")
    list_filter = ("media_type", "is_active")
    search_fields = ("caption",)
    ordering = ("display_order", "-uploaded_at")
    readonly_fields = ("preview", "uploaded_at")
    fields = (
        "media_type", "image", "video", "video_poster", "preview",
        "caption", "display_order", "is_active", "uploaded_at",
    )
    # Shows/hides the image vs. video fields in the add/change form
    # depending on the selected Media Type, so staff aren't confused by
    # irrelevant fields - see static/js/admin/gallery_media_toggle.js.
    class Media:
        js = ("js/admin/gallery_media_toggle.js",)

    def thumbnail(self, obj):
        if obj.is_video:
            poster = obj.video_poster
            if poster:
                return format_html(
                    '<img src="{}" style="width:70px;height:70px;object-fit:cover;border-radius:6px;'
                    'opacity:.85;">', poster.url,
                )
            return format_html(
                '<div style="width:70px;height:70px;border-radius:6px;background:#222;color:#fff;'
                'display:flex;align-items:center;justify-content:center;font-size:22px;">{}</div>',
                "▶",
            )
        if not obj.image:
            return "—"
        return format_html(
            '<img src="{}" style="width:70px;height:70px;object-fit:cover;border-radius:6px;">', obj.image.url,
        )
    thumbnail.short_description = "Preview"

    def preview(self, obj):
        if obj.is_video:
            if not obj.video:
                return "Upload and save to see a preview."
            poster_attr = format_html('poster="{}"', obj.video_poster.url) if obj.video_poster else ""
            return format_html(
                '<video src="{}" {} controls style="max-width:360px;max-height:360px;border-radius:8px;">'
                '</video>', obj.video.url, poster_attr,
            )
        if not obj.image:
            return "Upload and save to see a preview."
        return format_html(
            '<img src="{}" style="max-width:360px;max-height:360px;border-radius:8px;">', obj.image.url,
        )
    preview.short_description = "Preview"
