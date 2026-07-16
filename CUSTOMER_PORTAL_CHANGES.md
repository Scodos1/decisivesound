# Customer Portal — Implementation Notes

## Setup
1. `pip install -r requirements.txt --break-system-packages` (no new dependencies beyond what
   the Analytics feature already added - auth uses Django's own `django.contrib.auth`).
2. `python manage.py migrate` (applies `booking/migrations/0010_booking_user_cancellationrequest_customerprofile_and_more.py`).
3. In production, set real SMTP env vars (`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, etc.) so
   password-reset emails and cancellation-decision emails actually deliver - same `.env` you
   already use for booking notifications.

## Design decisions worth knowing about

**Auth is Django's own, not custom.** Registration/profile forms are custom, but login,
logout, and password reset all use `django.contrib.auth`'s built-in class-based views
(`LoginView`, `LogoutView`, `PasswordReset*View`) wired directly in `urls.py` with your own
templates. This means password hashing, reset-token generation/expiry, and session handling
are all the same well-audited code every other Django site uses - nothing security-critical was
hand-rolled.

**Email doubles as username.** `CustomerRegisterForm` sets `User.username = User.email`, so
customers only ever see "Email" on the login/register pages, never "Username". Enforced unique
in `clean_email()` since `User.email` isn't unique by default.

**Legacy bookings auto-link on registration.** Every booking before the portal existed (and
every booking a not-yet-registered customer makes) has `Booking.user = None`. When someone
registers, `portal_views.register()` attaches any existing booking whose `email` matches the
new account (case-insensitive) - so a repeat customer's first login already shows their history
instead of an empty dashboard. New bookings a *logged-in* customer submits are auto-linked too
(see `views._get_or_create_booking`).

**Ownership check = the query, not a permission flag.** Every booking-scoped portal view does
`get_object_or_404(Booking, pk=booking_id, user=request.user)`. A booking that exists but
belongs to someone else 404s exactly like one that doesn't exist at all - this is deliberate,
so the portal never leaks "that booking id exists, you just can't see it."

**Cancellation requires approval, by design.** A customer's "Request Cancellation" button
creates a `CancellationRequest` (status Pending) - it does **not** touch `Booking.status`.
Staff approve/reject it from Django Admin (`Cancellation Requests` - bulk actions
`approve_requests` / `reject_requests`). Approving is what actually sets the booking to
Cancelled (which in turn fires the existing cancellation email via `Booking.save()`), plus a
separate "your request was approved" email/notification. Rejecting leaves the booking
untouched.

**In-portal notifications piggyback on existing email sends.** Rather than a parallel
notification system, `notifications._notify_customer()` is called from inside the *existing*
`send_status_change_email`, `send_payment_receipt`, `send_quotation_email`, and
`send_invoice_email` functions - so the Dashboard's "Recent Notifications" panel and the
customer's inbox can never drift out of sync. It's a no-op for bookings with no linked account.

**Email verification is not enforced** (per the spec: "optional for MVP"). Accounts are active
immediately on registration; `CustomerProfile.email_verified` exists as a field for a future
verification-link flow but nothing currently sets it to True or gates access on it.

## What was added

| File | What |
|---|---|
| `booking/models.py` | `Booking.user` FK (nullable); new `CustomerProfile`, `Notification`, `CancellationRequest` models |
| `booking/forms.py` | `CustomerRegisterForm`, `CustomerProfileForm`, `CustomerAuthenticationForm`, `CancellationRequestForm` |
| `booking/portal_views.py` (new) | register, dashboard, booking detail, quotation/invoice download, cancellation request, profile |
| `booking/notifications.py` | `_notify_customer()` helper + hooks into every existing send_* function; new cancellation-decision emails |
| `booking/admin.py` | `CustomerProfileAdmin`, `NotificationAdmin`, `CancellationRequestAdmin` (with approve/reject actions) |
| `booking/urls.py` | `/portal/...` routes (auth + portal pages) |
| `decisivesounds/settings.py` | `LOGIN_URL`, `LOGIN_REDIRECT_URL`, `LOGOUT_REDIRECT_URL` |
| `templates/booking/portal/*.html` (new) | register, login, password reset (4 pages) + email, dashboard, booking detail, profile, shared nav/footer/head/messages partials |
| `templates/booking/{index,booking,payment,payment_success,booking_success}.html` | added a My Account / Log In link to the nav; booking_success also nudges anonymous customers to create an account |

## Known limitations / good next steps
- **Mobile nav** on the public marketing pages (`.nav-mobile`) wasn't given the My Account
  link - only the desktop `.nav-cta` was, plus the portal's own pages (which do have it on
  mobile too). Small, contained addition if wanted.
- The other public pages (About/Services/Gallery/Equipment/Contact/Terms) weren't touched -
  only the highest-traffic entry points (Home, Booking, Booking Success, Payment, Payment
  Success) got the nav link. Same one-line change would extend it to the rest.
- Email verification is scaffolded (`CustomerProfile.email_verified`) but not wired up - fine
  per spec ("optional for MVP"), but worth flagging if you want it enforced later.
- "Venue" in the spec maps to the existing `Booking.address` field - there's no separate venue
  field in the model.
