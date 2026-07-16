# Analytics & Reporting Dashboard — Implementation Notes

## Setup
1. `pip install -r requirements.txt --break-system-packages` (adds `openpyxl` for the Excel
   report export; `xhtml2pdf` was already required).
2. `python manage.py migrate` (applies `booking/migrations/0009_equipmentmaintenancelog.py`).

## What was added

**booking/constants.py** (new)
- `DASHBOARD_STATUS_COLORS`, `PAYMENT_STATUS_GROUPS`, `payment_status_for()` — pulled out of
  `views.py` so the new `analytics.py` / `reports.py` modules can reuse them without a
  circular import (`views.py` imports both of those, so they can't import back into `views.py`).
  `views.py` now imports from here too; nothing about its behavior changed.

**booking/models.py**
- New `EquipmentMaintenanceLog` model: `equipment` (FK), `quantity`, `reason`, `started_at`,
  `resolved_at` (blank = still ongoing), `notes`. This is what actually gives the dashboard's
  "Maintenance History" panel something to show — `EquipmentInventory.maintenance_quantity`
  is still just a live counter admins edit by hand, and this log doesn't auto-adjust it.
  Log entries are added from Django Admin (`Equipment Maintenance Logs`).

**booking/analytics.py** (new)
- Pure, read-only data-computation layer — one function per metric group from the spec:
  `kpis()`, `revenue_summary()` / `revenue_trend()`, `booking_analytics()` (event type / state /
  monthly trend / peak day-of-week), `payment_analytics()`, `equipment_analytics()` (inventory
  table, month-to-date headset utilization rate, maintenance history), `calendar_insights()`
  (today's events, this week, busy dates, inventory-conflict dates over the next 90 days).
- `dashboard_json_payload()` combines all of the above into one JSON-serializable dict. This is
  the single source of truth used by **both** the initial page render and the auto-refresh
  polling endpoint, so they can never disagree.
- Headset utilization rate = headset-days booked so far this month ÷ headset-days available
  (capacity × days elapsed). "Most frequently rented equipment" is honest about the same
  limitation noted in `EquipmentInventory`'s docstring: only Headsets are actually tied to
  bookings today, so Transmitters/Charging Cases will always show 0 reserved until a per-booking
  field is added for them.

**booking/reports.py** (new)
- `filter_bookings(params)` — shared filtering (event-date range, status, event type, state,
  payment status) for all three export formats.
- `export_csv()` / `export_excel()` (via `openpyxl`) / `export_pdf()` (via `xhtml2pdf`, reusing
  `documents.render_pdf()` — a small public wrapper added around `documents.py`'s existing
  private `_render_pdf()` helper).

**booking/views.py** — new staff-only endpoints:
| Action | URL name | Path |
|---|---|---|
| Analytics dashboard page | `analytics_dashboard` | `/dashboard/analytics/` |
| Auto-refresh JSON (polled every 30s client-side) | `analytics_data` | `/dashboard/analytics/data/` |
| Export report (CSV/Excel/PDF) | `analytics_report` | `/dashboard/analytics/report/?format=csv\|xlsx\|pdf` |

`_payment_status_for` in `views.py` is now a thin alias for `constants.payment_status_for` —
every existing call site was left untouched.

**templates/booking/analytics_dashboard.html** (new)
- Matches the existing dashboard's dark theme/sidebar (same CSS variables/layout as
  `admin_dashboard.html` and `dashboard_calendar.html` — not the public-site "Silent Pulse"
  theme, since this is an internal staff page).
- Charts via Chart.js (loaded from `cdn.jsdelivr.net`, same CDN-via-`<script>` pattern already
  in the spirit of this project's vanilla-JS front end): revenue-over-time line chart, bookings
  by event type / by state, booking trend by month, peak-period bar chart.
- Auto-refresh: `fetch()`-polls `analytics_data` every 30s and patches KPI numbers + all five
  charts in place — no full-page reload, no websockets/Channels dependency needed for this MVP.
- Reports panel: date range + status/event-type/state/payment-status filters, three export
  buttons (CSV / Excel / PDF) that submit the filter form as query params to `analytics_report`.

**templates/booking/documents/report_pdf.html** (new)
- Follows the same xhtml2pdf-safe layout conventions (plain tables, no flexbox/grid) as
  `quotation_pdf.html` / `invoice_pdf.html`.

**booking/admin.py**
- Registers `EquipmentMaintenanceLog` with an Ongoing/Resolved status badge.

**Sidebar navigation**
- Added a "📈 Analytics" link to `admin_dashboard.html` and `dashboard_calendar.html`'s
  sidebars, plus a "View Analytics" quick-action button on the main dashboard.

## Not implemented / known limitations
- **Real-time** here means polling (every 30s), not websockets/Server-Sent Events — appropriate
  for a small internal dashboard's MVP, but worth knowing if "real-time" ever needs to mean
  sub-second.
- Equipment analytics (utilization, "most frequently rented") is only meaningful for Headsets
  today, per the existing model design — see `EquipmentInventory`'s docstring.
- The report date-range filter applies to **event date**, not booking-created date; if you also
  want a "created between" filter, that's a small addition to `reports.filter_bookings()`.
