import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

# Pricing constants - shared by the dashboard revenue math, the WhatsApp
# message, and every outbound email that quotes a price.
RATE_PER_HEADSET = 1500
SERVICE_CHARGE = 80000
CAUTION_FEE = 80000

# VAT/tax rate applied to quotations and invoices, as a fraction (0.075 =
# 7.5%). Kept at 0 until the business is VAT-registered - the "Taxes"
# line on documents shows "N/A" whenever this is 0 (see documents.py).
TAX_RATE = 0

# How many days a generated quotation stays valid for before it's
# considered expired (shown to the customer as the "Quotation Expiry
# Date" and used to badge stale quotations on the dashboard).
QUOTATION_VALIDITY_DAYS = 14


class Booking(models.Model):
    EVENT_TYPES = [
        ("Wedding", "Wedding"),
        ("Birthday Party", "Birthday Party"),
        ("Corporate Event", "Corporate Event"),
        ("Beach Party", "Beach Party"),
        ("School Event", "School Event"),
        ("Church Event", "Church Event"),
        ("Festival", "Festival"),
        ("Private Party", "Private Party"),
        ("Other", "Other"),
    ]

    STATUS_PENDING = "Pending"
    STATUS_CONFIRMED = "Confirmed"
    STATUS_DEPOSIT_PAID = "Deposit Paid"
    STATUS_FULLY_PAID = "Fully Paid"
    STATUS_COMPLETED = "Completed"
    STATUS_CANCELLED = "Cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_DEPOSIT_PAID, "Deposit Paid"),
        (STATUS_FULLY_PAID, "Fully Paid"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]
    # Statuses that hold a headset reservation against inventory for their
    # event date (see EquipmentInventory below). Pending never reserves;
    # Cancelled/Completed release by definition (they're excluded here, so
    # they simply stop counting toward "already reserved" on their date).
    RESERVING_STATUSES = (STATUS_CONFIRMED, STATUS_DEPOSIT_PAID, STATUS_FULLY_PAID)

    # --- Quotation & invoice document lifecycle ---
    QUOTATION_NOT_GENERATED = "Not Generated"
    QUOTATION_GENERATED = "Generated"
    QUOTATION_SENT = "Sent"
    QUOTATION_EXPIRED = "Expired"
    QUOTATION_STATUS_CHOICES = [
        (QUOTATION_NOT_GENERATED, "Not Generated"),
        (QUOTATION_GENERATED, "Generated"),
        (QUOTATION_SENT, "Sent"),
        (QUOTATION_EXPIRED, "Expired"),
    ]

    INVOICE_NOT_GENERATED = "Not Generated"
    INVOICE_GENERATED = "Generated"
    INVOICE_SENT = "Sent"
    INVOICE_STATUS_CHOICES = [
        (INVOICE_NOT_GENERATED, "Not Generated"),
        (INVOICE_GENERATED, "Generated"),
        (INVOICE_SENT, "Sent"),
    ]

    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    # Nullable: every booking made before the Customer Portal existed (and
    # every booking a not-yet-registered customer submits) has no account
    # yet. See portal_views.register - registering auto-attaches any
    # existing bookings whose email matches the new account.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="bookings",
    )
    event_type = models.CharField(max_length=30, choices=EVENT_TYPES)
    event_date = models.DateField()
    state = models.CharField(max_length=100)
    address = models.TextField()
    guests = models.PositiveIntegerField()
    headsets = models.PositiveIntegerField()
    duration = models.PositiveIntegerField()

    message = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    # --- Payment (see PaymentTransaction below for the full attempt log,
    # including failed/unverified attempts). These four fields always
    # reflect only the latest VERIFIED payment - never trust anything
    # else to write to them. ---
    payment_reference = models.CharField(max_length=100, blank=True)
    amount_paid = models.PositiveIntegerField(default=0)
    payment_date = models.DateTimeField(null=True, blank=True)
    payment_method = models.CharField(max_length=30, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # --- Quotation & invoice document fields ---
    # null=True (not just blank) so "not yet generated" rows don't collide
    # on the unique constraint - only actually-assigned numbers are ever
    # compared, and once assigned a number is never reassigned.
    quotation_number = models.CharField(max_length=30, null=True, blank=True, unique=True)
    quotation_generated_at = models.DateTimeField(null=True, blank=True)
    quotation_expiry_date = models.DateField(null=True, blank=True)
    quotation_status = models.CharField(
        max_length=20, choices=QUOTATION_STATUS_CHOICES, default=QUOTATION_NOT_GENERATED,
    )

    invoice_number = models.CharField(max_length=30, null=True, blank=True, unique=True)
    invoice_generated_at = models.DateTimeField(null=True, blank=True)
    invoice_status = models.CharField(
        max_length=20, choices=INVOICE_STATUS_CHOICES, default=INVOICE_NOT_GENERATED,
    )

    PAYMENT_DEPOSIT = "deposit"
    PAYMENT_FULL = "full"
    PAYMENT_TYPE_CHOICES = [
        (PAYMENT_DEPOSIT, "Deposit"),
        (PAYMENT_FULL, "Full Amount"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Snapshot the status as loaded from the DB (or the default, for a
        # brand-new unsaved instance) so save() can tell whether it changed.
        self._original_status = self.status

    def __str__(self):
        return f"{self.name} - {self.event_type}"

    def clean(self):
        """Runs automatically through any ModelForm save (i.e. the Django
        Admin single-booking change form) - blocks saving a booking in a
        reserving status if it would exceed available headset inventory
        for its event date. Bulk admin actions and the dashboard's Confirm
        button don't go through a ModelForm, so they call
        insufficient_headset_availability() directly instead - see
        admin.py:_bulk_set_status and views.py:dashboard_booking_action."""
        super().clean()
        if self.status in self.RESERVING_STATUSES:
            reason = self.insufficient_headset_availability()
            if reason:
                raise ValidationError({"status": reason})

    def insufficient_headset_availability(self):
        """None if it's fine to reserve self.headsets on self.event_date;
        otherwise a human-readable reason to show the admin. Only checks
        headsets - see EquipmentInventory for why Transmitters/Charging
        Cases aren't part of this check yet. If no Headset inventory row
        has been configured at all, this never blocks (fail open, not
        closed, so bookings aren't silently stuck before setup is done)."""
        try:
            inventory = EquipmentInventory.objects.get(equipment_type=EQUIPMENT_HEADSET)
        except EquipmentInventory.DoesNotExist:
            return None
        already_reserved = Booking.objects.filter(
            status__in=self.RESERVING_STATUSES, event_date=self.event_date,
        ).exclude(pk=self.pk).aggregate(total=models.Sum("headsets"))["total"] or 0
        available = inventory.total_quantity - inventory.maintenance_quantity - already_reserved
        if self.headsets > available:
            return (
                f"Insufficient inventory available for {self.event_date}: "
                f"only {max(available, 0)} headset(s) available, {self.headsets} requested."
            )
        return None

    def estimated_total(self):
        """Numeric estimated total for this booking - used by the dashboard
        revenue figures and the pricing breakdown in emails/WhatsApp."""
        rental = self.headsets * RATE_PER_HEADSET
        service_charge = SERVICE_CHARGE if self.state == "Lagos" else 0
        return rental + service_charge + CAUTION_FEE

    def details_text(self):
        """Plain-text breakdown of this booking - shared by every email and
        the WhatsApp message so none of them ever drift out of sync."""
        is_lagos = self.state == "Lagos"
        rental = self.headsets * RATE_PER_HEADSET
        total = self.estimated_total()

        service_charge_line = f"₦{SERVICE_CHARGE:,}" if is_lagos else "To be confirmed"
        total_line = f"₦{total:,}" if is_lagos else "To be confirmed"

        return (
            f"Name:             {self.name}\n"
            f"Phone:            {self.phone}\n"
            f"Email:            {self.email or '—'}\n"
            f"Event type:       {self.event_type}\n"
            f"Event date:       {self.event_date}\n"
            f"State:            {self.state}\n"
            f"Venue location:   {self.address}\n"
            f"Guests:           {self.guests}\n"
            f"Headsets needed:  {self.headsets}\n"
            f"Duration:         {self.duration} hrs\n"
            f"Notes:            {self.message}\n\n"
            "─── Estimated pricing breakdown ───\n"
            f"Headset rental:   ₦{rental:,}\n"
            f"Service charge:   {service_charge_line}\n"
            f"Caution fee:      ₦{CAUTION_FEE:,}\n"
            "─────────────────────────────────\n"
            f"Total to confirm: {total_line}"
        )

    def save(self, *args, skip_status_email=False, **kwargs):
        is_new = self._state.adding
        status_changed = (not is_new) and (self.status != self._original_status)
        old_status = self._original_status
        new_status = self.status

        super().save(*args, **kwargs)

        if status_changed and not skip_status_email:
            # Imported here (not at module level) to avoid a circular
            # import - notifications.py imports Booking from this module.
            from . import notifications
            notifications.send_status_change_email(self, old_status, self.status)

        self._original_status = self.status

        # Auto-generate + email the quotation the moment a booking becomes
        # Confirmed (see the Quotation Workflow in the feature spec: Admin
        # reviews booking -> Quotation Generated -> Email quotation). The
        # "not self.quotation_number" guard makes this a no-op on any save
        # that isn't the actual Pending->Confirmed transition, including
        # the recursive save() inside generate_quotation() itself below -
        # so this never loops and never re-sends on later saves.
        if status_changed and new_status == self.STATUS_CONFIRMED and not self.quotation_number:
            self.generate_quotation()
            from . import notifications
            notifications.send_quotation_email(self)

    # ------------------------------------------------------------------
    # Payment
    # ------------------------------------------------------------------

    @property
    def full_price_known(self):
        """The service charge (and therefore the full total) is only a
        fixed, known number for Lagos bookings - everywhere else it's
        "to be confirmed" by staff. Paying the FULL amount online only
        makes sense once that number is actually fixed."""
        return self.state == "Lagos"

    @property
    def can_pay_deposit(self):
        """Deposit-only payment has been disabled - customers only ever
        pay the full amount now. Kept as a property (always False) rather
        than deleted outright so the STATUS_DEPOSIT_PAID status, CAUTION_FEE
        constant, and historical deposit-paid bookings/reporting all keep
        working unchanged - this only turns off *new* deposit payments."""
        return False

    @property
    def can_pay_full(self):
        """Full/remaining amount: payable from Pending or Confirmed (pays
        everything), or from Deposit Paid (pays the remaining balance, for
        bookings that already have one on file from before deposits were
        disabled) - but only once the total is actually a fixed number."""
        if not self.full_price_known:
            return False
        return self.status in (self.STATUS_PENDING, self.STATUS_CONFIRMED, self.STATUS_DEPOSIT_PAID)

    @property
    def can_pay(self):
        return self.can_pay_deposit or self.can_pay_full

    def amount_due(self, payment_type):
        """Amount in Naira (not kobo) for the given payment_type, given
        this booking's current status. Raises ValueError if that payment
        type isn't actually available right now - callers must check
        can_pay_deposit / can_pay_full first."""
        if payment_type == self.PAYMENT_DEPOSIT:
            if not self.can_pay_deposit:
                raise ValueError("Deposit is not payable for this booking right now.")
            return CAUTION_FEE

        if payment_type == self.PAYMENT_FULL:
            if not self.can_pay_full:
                raise ValueError("Full payment is not payable for this booking right now.")
            if self.status == self.STATUS_DEPOSIT_PAID:
                # Remaining balance after the deposit already paid.
                return self.estimated_total() - CAUTION_FEE
            return self.estimated_total()

        raise ValueError(f"Unknown payment_type: {payment_type!r}")

    def record_verified_payment(self, *, reference, amount, method, payment_type, paid_at):
        """Apply a verified Paystack payment to this booking: updates the
        summary fields and moves status forward. Does NOT send emails or
        touch PaymentTransaction - callers (views.py) handle those, so this
        stays a pure, easily-testable state transition."""
        self.payment_reference = reference
        self.amount_paid = self.amount_paid + amount
        self.payment_date = paid_at
        self.payment_method = method
        self.status = self.STATUS_FULLY_PAID if payment_type == self.PAYMENT_FULL else self.STATUS_DEPOSIT_PAID
        # skip_status_email=True: the generic "your booking is now Deposit
        # Paid" email would be redundant here - views.py sends a proper
        # payment receipt (amount, reference, date) instead once this
        # returns. The generic email still fires for MANUAL status changes
        # (e.g. staff marking Deposit Paid after an offline bank transfer).
        self.save(skip_status_email=True)
        # Invoice Workflow: Payment Successful -> Invoice Generated. Every
        # verified payment (deposit or full) regenerates the invoice's
        # snapshot fields so amount-paid/outstanding-balance stay current -
        # generate_invoice() reuses the same invoice_number once assigned,
        # so this is a refresh, not a new document. views.py sends the
        # actual email alongside the existing payment-receipt email.
        self.generate_invoice()

    # ------------------------------------------------------------------
    # Quotation & invoice document generation
    # ------------------------------------------------------------------

    def generate_quotation(self):
        """Assigns a quotation number the first time this is called;
        later calls (e.g. staff clicking "Generate Quote" again) keep the
        same number and just refresh the generated date, expiry, and
        status - so a quotation number is never reassigned or duplicated.
        Data-only: callers are responsible for emailing/downloading it."""
        if not self.quotation_number:
            self.quotation_number = f"QUO-{timezone.localdate().year}-{self.pk:05d}"
        self.quotation_generated_at = timezone.now()
        self.quotation_expiry_date = timezone.localdate() + timedelta(days=QUOTATION_VALIDITY_DAYS)
        self.quotation_status = self.QUOTATION_GENERATED
        self.save(skip_status_email=True)

    def generate_invoice(self):
        """Assigns an invoice number the first time this is called; later
        calls (e.g. a second payment, or staff clicking "Generate Invoice"
        again) keep the same number and just refresh the generated date
        and status. Data-only: callers are responsible for emailing/
        downloading it."""
        if not self.invoice_number:
            self.invoice_number = f"INV-{timezone.localdate().year}-{self.pk:05d}"
        self.invoice_generated_at = timezone.now()
        self.invoice_status = self.INVOICE_GENERATED
        self.save(skip_status_email=True)

    def mark_quotation_sent(self):
        if self.quotation_status != self.QUOTATION_SENT:
            self.quotation_status = self.QUOTATION_SENT
            self.save(skip_status_email=True)

    def mark_invoice_sent(self):
        if self.invoice_status != self.INVOICE_SENT:
            self.invoice_status = self.INVOICE_SENT
            self.save(skip_status_email=True)

    @property
    def quotation_is_expired(self):
        return bool(self.quotation_expiry_date) and timezone.localdate() > self.quotation_expiry_date


# ---------------------------------------------------------------------
# Equipment inventory
# ---------------------------------------------------------------------

EQUIPMENT_HEADSET = "Headset"
EQUIPMENT_TRANSMITTER = "Transmitter"
EQUIPMENT_CHARGING_CASE = "Charging Case"
EQUIPMENT_TYPE_CHOICES = [
    (EQUIPMENT_HEADSET, "Silent Disco Headset"),
    (EQUIPMENT_TRANSMITTER, "Audio Transmitter"),
    (EQUIPMENT_CHARGING_CASE, "Charging Case"),
]


class EquipmentInventory(models.Model):
    """
    Business-wide stock levels per equipment type (one row each). Only
    'Headset' actually gates booking confirmations - the booking form
    only ever asks customers for a headset count (Booking.headsets), so
    there's no per-booking demand figure for Transmitters or Charging
    Cases yet. Those rows are still stock-tracked here (admins can add
    them, edit quantities, mark units under maintenance) for the
    dashboard's Inventory Summary, but nothing auto-reserves them. Add a
    matching field to Booking + the booking form before relying on them
    to prevent overbooking the way Headsets do.

    Reserved/Available are intentionally NOT stored fields, even though a
    running counter is what the "lifecycle" (Available -> Reserved -> In
    Use -> Returned) suggests. A single global counter would incorrectly
    block a booking on one date just because unrelated bookings on a
    totally different date haven't been marked Completed yet. Instead,
    reserved/available are always computed live for a specific event
    date, so different dates never compete for the same stock - equipment
    committed to an Aug 12 event is automatically free again for Aug 13.
    """
    name = models.CharField(max_length=100)
    equipment_type = models.CharField(max_length=30, choices=EQUIPMENT_TYPE_CHOICES, unique=True)
    total_quantity = models.PositiveIntegerField(default=0)
    maintenance_quantity = models.PositiveIntegerField(
        default=0, help_text="Units currently out of service and unavailable for booking."
    )
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Equipment Inventory"
        verbose_name_plural = "Equipment Inventory"
        ordering = ["equipment_type"]

    def __str__(self):
        return f"{self.name} ({self.get_equipment_type_display()})"

    def reserved_on(self, event_date):
        """Units committed to Confirmed/Deposit Paid/Fully Paid bookings on
        this exact event date."""
        if self.equipment_type != EQUIPMENT_HEADSET:
            return 0
        return Booking.objects.filter(
            status__in=Booking.RESERVING_STATUSES, event_date=event_date,
        ).aggregate(total=models.Sum("headsets"))["total"] or 0

    def available_on(self, event_date):
        return max(self.total_quantity - self.maintenance_quantity - self.reserved_on(event_date), 0)

    def reserved_today(self):
        return self.reserved_on(timezone.localdate())

    def available_today(self):
        return self.available_on(timezone.localdate())


class EquipmentMaintenanceLog(models.Model):
    """
    A record of equipment being taken out of service for maintenance/
    repair and (once resolved) put back. This is distinct from
    EquipmentInventory.maintenance_quantity, which is just the current
    live count admins keep in sync by hand - that field alone can't answer
    "what happened, and when" for the Analytics dashboard's Maintenance
    History. This table is purely a log: saving it does NOT automatically
    adjust maintenance_quantity, so admins still update that field
    themselves when equipment actually goes down or comes back.
    """
    equipment = models.ForeignKey(
        EquipmentInventory, on_delete=models.CASCADE, related_name="maintenance_logs"
    )
    quantity = models.PositiveIntegerField(default=1, help_text="Number of units affected.")
    reason = models.CharField(max_length=200, blank=True)
    started_at = models.DateField(default=timezone.localdate)
    resolved_at = models.DateField(
        null=True, blank=True, help_text="Leave blank while the units are still under maintenance."
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at", "-created_at"]
        verbose_name = "Equipment Maintenance Log"
        verbose_name_plural = "Equipment Maintenance Logs"

    def __str__(self):
        status = "Ongoing" if not self.resolved_at else f"Resolved {self.resolved_at}"
        return f"{self.equipment.name} x{self.quantity} - {status}"

    @property
    def is_ongoing(self):
        return self.resolved_at is None


class PaymentTransaction(models.Model):
    """
    Full audit log of every payment attempt against a booking - both
    successful and failed/unverified ones. Booking's own payment_* fields
    only ever reflect the latest SUCCESSFUL payment; this table is the
    system of record for everything, including the failures admins need
    to be able to review.
    """
    STATUS_PENDING = "Pending"
    STATUS_SUCCESS = "Success"
    STATUS_FAILED = "Failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    booking = models.ForeignKey(
        "Booking", on_delete=models.CASCADE, related_name="payment_transactions"
    )
    reference = models.CharField(max_length=100, unique=True)
    payment_type = models.CharField(max_length=10, choices=Booking.PAYMENT_TYPE_CHOICES)
    amount = models.PositiveIntegerField(help_text="Amount in Naira")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    gateway_response = models.TextField(
        blank=True, help_text="Raw response/error from Paystack, for admin review"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} - {self.status} - ₦{self.amount:,}"


# ---------------------------------------------------------------------
# Customer Portal
# ---------------------------------------------------------------------

class CustomerProfile(models.Model):
    """
    One row per registered customer account, alongside the built-in
    Django User (which already covers email/first_name/last_name/
    password). Auth itself deliberately uses stock django.contrib.auth -
    this table only holds the extra field the portal's Profile page needs
    that User doesn't have: phone number.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="customer_profile")
    phone = models.CharField(max_length=20, blank=True)
    email_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Profile: {self.user.get_full_name() or self.user.username}"


class Notification(models.Model):
    """
    In-portal notification feed (Customer Dashboard > Recent Notifications)
    - a lightweight companion to the email notifications in notifications.py,
    not a replacement for them. Created alongside the matching email by
    notifications._notify_customer() so the two channels always agree
    with each other. Only ever created for bookings that belong to a
    registered account (booking.user is set) - anonymous bookings have
    nowhere in the portal to show a notification.
    """
    TYPE_BOOKING_CONFIRMED = "booking_confirmed"
    TYPE_PAYMENT_RECEIVED = "payment_received"
    TYPE_QUOTATION_GENERATED = "quotation_generated"
    TYPE_INVOICE_GENERATED = "invoice_generated"
    TYPE_EVENT_REMINDER = "event_reminder"
    TYPE_BOOKING_COMPLETED = "booking_completed"
    TYPE_BOOKING_CANCELLED = "booking_cancelled"
    TYPE_CANCELLATION_REQUESTED = "cancellation_requested"
    TYPE_CANCELLATION_DECIDED = "cancellation_decided"
    TYPE_CHOICES = [
        (TYPE_BOOKING_CONFIRMED, "Booking Confirmed"),
        (TYPE_PAYMENT_RECEIVED, "Payment Received"),
        (TYPE_QUOTATION_GENERATED, "Quotation Generated"),
        (TYPE_INVOICE_GENERATED, "Invoice Generated"),
        (TYPE_EVENT_REMINDER, "Event Reminder"),
        (TYPE_BOOKING_COMPLETED, "Booking Completed"),
        (TYPE_BOOKING_CANCELLED, "Booking Cancelled"),
        (TYPE_CANCELLATION_REQUESTED, "Cancellation Requested"),
        (TYPE_CANCELLATION_DECIDED, "Cancellation Request Decided"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    notif_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_notif_type_display()} - {self.user}"


class CancellationRequest(models.Model):
    """
    A customer-initiated 'please cancel my booking' request - kept
    separate from just setting Booking.status=Cancelled directly so an
    admin can review and approve/reject it first (spec: "subject to
    approval"). Approving transitions the booking to Cancelled and fires
    the existing cancellation email (see Booking.save()); rejecting
    leaves the booking untouched. Either way the customer gets a
    Notification + email about the decision - see admin.py's approve/
    reject actions.
    """
    STATUS_PENDING = "Pending"
    STATUS_APPROVED = "Approved"
    STATUS_REJECTED = "Rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="cancellation_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cancellation_requests")
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    admin_note = models.CharField(max_length=255, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Cancellation request for booking #{self.booking_id} ({self.status})"

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING


class GalleryImage(models.Model):
    """
    Public Gallery page media (templates/booking/gallery.html), managed
    entirely from Django Admin - see admin.py's GalleryImageAdmin. Untagged:
    staff just upload a photo or a video clip and an optional caption, no
    category needed. Kept as a single model (rather than splitting photos
    and videos into separate tables) so the public page can render one
    unified, orderable grid.
    """

    MEDIA_IMAGE = "image"
    MEDIA_VIDEO = "video"
    MEDIA_TYPE_CHOICES = [
        (MEDIA_IMAGE, "Photo"),
        (MEDIA_VIDEO, "Video"),
    ]

    # Long edge any uploaded photo gets downscaled to on save (see
    # _optimize_image()) - keeps a phone photo straight out of the camera
    # from shipping as a multi-megabyte file to every visitor of the
    # public Gallery page. Videos are left as-is (re-encoding video needs
    # ffmpeg, which isn't available here) - see GALLERY_MANAGEMENT_CHANGES.md
    # for the recommended upload size for staff.
    MAX_DIMENSION = 1600

    media_type = models.CharField(
        max_length=5, choices=MEDIA_TYPE_CHOICES, default=MEDIA_IMAGE,
        help_text="Whether this entry is a photo or a video clip.",
    )
    image = models.ImageField(
        upload_to="gallery/", blank=True, null=True,
        help_text="Required for Photo entries. Ignored for Video entries.",
    )
    video = models.FileField(
        upload_to="gallery/videos/", blank=True, null=True,
        validators=[FileExtensionValidator(allowed_extensions=["mp4", "webm", "mov", "m4v"])],
        help_text="Required for Video entries (mp4/webm/mov). Ignored for Photo entries. Keep clips short "
                   "(under ~30s) and compressed - large files slow down the public Gallery page for visitors.",
    )
    video_poster = models.ImageField(
        upload_to="gallery/video_posters/", blank=True, null=True,
        help_text="Optional cover image shown before a video plays. If left blank, the browser shows the "
                   "video's first frame instead.",
    )
    caption = models.CharField(
        max_length=150, blank=True,
        help_text="Shown as the small tag overlay on the photo/video, and as its alt text. Optional.",
    )
    display_order = models.PositiveIntegerField(
        default=0, help_text="Lower numbers appear first. Entries with the same number fall back to newest-first.",
    )
    is_active = models.BooleanField(default=True, help_text="Uncheck to hide from the public Gallery page without deleting it.")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "-uploaded_at"]
        verbose_name = "Gallery Item"
        verbose_name_plural = "Gallery Items"

    def __str__(self):
        return self.display_caption

    @property
    def display_caption(self):
        return self.caption or ("Gallery video" if self.is_video else "Gallery photo")

    @property
    def is_video(self):
        return self.media_type == self.MEDIA_VIDEO

    def clean(self):
        if self.media_type == self.MEDIA_IMAGE and not self.image:
            raise ValidationError({"image": "An image file is required for Photo entries."})
        if self.media_type == self.MEDIA_VIDEO and not self.video:
            raise ValidationError({"video": "A video file is required for Video entries."})

    def save(self, *args, **kwargs):
        if self.media_type == self.MEDIA_IMAGE:
            self._optimize_image()
        if self.video_poster:
            self._optimize_video_poster()
        super().save(*args, **kwargs)

    def _optimize_image(self):
        self._optimize_image_field("image")

    def _optimize_video_poster(self):
        self._optimize_image_field("video_poster")

    def _optimize_image_field(self, field_name):
        """Downscales the upload to MAX_DIMENSION on its long edge and
        re-encodes as a reasonable-quality JPEG, if it isn't small enough
        already. Best-effort: if Pillow can't read the file for any reason
        (corrupt upload, unsupported format), the original file is left
        untouched rather than blocking the save. Shared by the main photo
        field and the optional video poster field."""
        field_file = getattr(self, field_name)
        if not field_file or not hasattr(field_file, "file"):
            return
        try:
            from io import BytesIO

            from django.core.files.uploadedfile import InMemoryUploadedFile
            from PIL import Image, ImageOps

            field_file.file.seek(0)
            img = Image.open(field_file.file)
            img = ImageOps.exif_transpose(img)  # respect phone camera orientation
            if img.mode != "RGB":
                img = img.convert("RGB")

            width, height = img.size
            if max(width, height) > self.MAX_DIMENSION:
                scale = self.MAX_DIMENSION / max(width, height)
                img = img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)

            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85, optimize=True)
            buffer.seek(0)

            name = field_file.name.rsplit(".", 1)[0] + ".jpg"
            setattr(self, field_name, InMemoryUploadedFile(
                buffer, "ImageField", name, "image/jpeg", buffer.getbuffer().nbytes, None,
            ))
        except Exception:
            logging.getLogger(__name__).exception("Gallery image optimization skipped for %s", field_file)
