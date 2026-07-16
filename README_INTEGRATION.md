# Decisive Sound NG — Django Website

This is the full project with the booking-form-to-database integration applied
(saving to DB, business + customer confirmation emails, WhatsApp handoff,
booking statuses, staff dashboard) plus a round of template bug fixes.

## Setup

```bash
cd DecisiveSoundsProject
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install django
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The database included here is freshly migrated and empty — no test bookings
in it. Create a superuser with the command above so you can log into
`/admin/`.

## What this integration added

- **Booking form → database.** `booking/views.py` validates with Django,
  saves to the existing `Booking` model, then redirects to a success page
  (`templates/booking/booking_success.html`) that auto-launches WhatsApp
  with the pre-filled booking message. The booking is saved regardless of
  what the customer does with WhatsApp afterward.
- **Business notification email** → `decisivesound8@gmail.com` on every new
  booking.
- **Customer confirmation email** → sent to the customer if they gave an
  email address.
  Both emails are best-effort: a failed send is logged and skipped — it
  never blocks the booking from saving or the customer from reaching
  WhatsApp.
- **Booking status** — `Pending` / `Confirmed` / `Completed` / `Cancelled`,
  editable from the admin (colored badges + bulk actions). Customers can't
  set this themselves.
- **Staff dashboard** at `/dashboard/` — total bookings, upcoming events,
  bookings by state, revenue estimates. Linked from the Booking list in
  admin via a "📊 View Dashboard" button. Requires a staff login.
- **Duplicate-submission protection** — an identical booking (same phone +
  event date + headset count) submitted again within 5 minutes reuses the
  existing row instead of creating a new one.
- Fixed a couple of pre-existing bugs along the way: the booking form's
  `<form>` tag was malformed (`<fo ...>`) with the submit button sitting
  outside it, and the event-type dropdown options didn't match the model's
  allowed choices.

## Template errors fixed (this broke `/about/`, `/contact/`, `/services/`, `/equipment/`, `/terms/`, `/gallery/`)

- `{% load static %}` was missing from most page templates, so any use of
  `{% static %}` crashed with `TemplateSyntaxError: Invalid block tag`.
- Several nav bars pointed at `{% url 'index' %}`, but the home page's URL
  name is actually `home` — this threw `NoReverseMatch` once the
  static-tag bug above was fixed.
- The footer "Rental Agreement" / "Privacy Policy" links pointed at
  `{% url 'rental' %}` and `{% url 'privacy' %}`, neither of which is a
  real URL name — also `NoReverseMatch`. Both now point at `terms`,
  matching every other page.
- `gallery.html` had never actually been converted to a Django template —
  it still used raw `href="about.html"`, `src="images/logo.png"`, etc.
  It's now fully wired up like the rest of the site.
- `static/css/animations.css` didn't exist on disk — the actual file was
  named `animations copy.css`, so that stylesheet 404'd on every page.
  Renamed to match what the templates reference.
- All eight public pages (`/`, `/about/`, `/services/`, `/equipment/`,
  `/gallery/`, `/contact/`, `/terms/`, `/booking/`) now render with a
  `200` — verified with an automated test pass.

One thing this didn't fix: `images/about.jpg`, `images/hero.jpg`, and every
file under `images/gallery/` and `images/equipment/` don't exist yet — those
folders are empty. The HTML already has `onerror` fallbacks so pages won't
break, but you'll want real photos there eventually.

## Booking status lifecycle

`Booking.status` now supports the full lifecycle:

```
Pending → Confirmed → Deposit Paid → Fully Paid → Completed
Pending → Cancelled   (alternate path)
```

- Every new booking defaults to **Pending** — no user interaction required.
- Customers can never see or set this field; it's excluded from `BookingForm`
  (`forms.py`) entirely, and I confirmed via an automated test that even a
  forged form submission with `status=Completed` is silently ignored — the
  booking still lands as Pending.
- Only staff can change it, from the Django admin (`booking/admin.py`):
  the Booking list shows a colored status badge, `status` is filterable,
  and there are bulk actions ("Mark selected as Confirmed", etc.) plus the
  normal per-record edit page.
- Search (`search_fields`) is independent of whatever status filter is
  active — searching always covers bookings in every status. Verified with
  an automated test.
- The staff dashboard (`/dashboard/`) shows a pill for each of the 6
  statuses, and revenue is now broken into three tiers: **Collected**
  (Fully Paid + Completed), **In-Progress** (Confirmed + Deposit Paid), and
  **Pending**. Cancelled bookings are excluded from all revenue figures.

Automated status-triggered notifications (e.g. auto-emailing the customer
when status flips to Confirmed) are intentionally **not** implemented yet —
the spec calls these out as future work. The status field and admin tooling
are in place and ready for that to hook into later.

## Switched to PostgreSQL

The project now uses PostgreSQL instead of SQLite (`decisivesounds/settings.py`).
I actually installed a real PostgreSQL server and ran the full test suite —
migrations, booking save, status lifecycle, admin filtering, the dashboard,
and all 8 public pages — against it, not just SQLite. Everything passed.

Setup on your machine:

1. Install PostgreSQL if you don't have it: https://www.postgresql.org/download/
   (or use a managed host — see option B below).
2. Create a database and note the connection details:
   ```sql
   CREATE DATABASE decisivesounds;
   ```
3. Add these to your `.env` (see `.env.example` for the template):
   ```
   DB_NAME=decisivesounds
   DB_USER=postgres
   DB_PASSWORD=your-postgres-password
   DB_HOST=localhost
   DB_PORT=5432
   ```
4. `pip install -r requirements.txt` (now includes `psycopg2-binary` and
   `dj-database-url`)
5. `python manage.py migrate` — this creates all tables fresh in Postgres.
   There's no `db.sqlite3` in this zip at all anymore.

**Option B — managed Postgres host** (Railway, Render, Supabase,
ElephantSQL, Heroku, etc.): instead of the four `DB_*` variables, set a
single `DATABASE_URL` in your `.env`:
```
DATABASE_URL=postgres://user:password@host:5432/dbname
```
This takes priority over the individual `DB_*` settings if both are present.

## Sending real emails

Right now `EMAIL_BACKEND` defaults to Django's console backend in
development (`DEBUG = True` in `decisivesounds/settings.py`), so emails
print to your terminal instead of actually sending. To have them really
deliver, set these environment variables wherever you run the server:

```
EMAIL_HOST_USER=your-gmail-address@gmail.com
EMAIL_HOST_PASSWORD=your-gmail-app-password
DEFAULT_FROM_EMAIL=your-gmail-address@gmail.com
```

(A Gmail "app password" is different from your normal password — generate
one under your Google Account's Security settings.)
