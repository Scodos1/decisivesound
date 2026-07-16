# Quotation & Invoice Management — Implementation Notes

## Setup
1. `pip install -r requirements.txt --break-system-packages` (adds `xhtml2pdf` for PDF rendering).
2. `python manage.py migrate` (applies `booking/migrations/0008_booking_quotation_invoice_fields.py`).

## What was added

**booking/models.py**
- `TAX_RATE` and `QUOTATION_VALIDITY_DAYS` constants (both easy to tune later).
- New `Booking` fields: `quotation_number`, `quotation_generated_at`, `quotation_expiry_date`,
  `quotation_status`, `invoice_number`, `invoice_generated_at`, `invoice_status`.
- `generate_quotation()` / `generate_invoice()` — idempotent: assign a number the first time,
  refresh dates/status on later calls, never reassign a number.
- `mark_quotation_sent()` / `mark_invoice_sent()` and a `quotation_is_expired` property.
- **Automatic generation is wired into the existing flows, not bolted on separately:**
  - `save()` generates + emails the quotation the moment a booking's status becomes `Confirmed`
    (matches the spec's Quotation Workflow exactly).
  - `record_verified_payment()` regenerates the invoice snapshot on every verified payment
    (deposit or full); `views.py` emails it right after, alongside the existing payment receipt.

**booking/documents.py** (new)
- Single source of truth for quotation/invoice content (`quotation_context()` /
  `invoice_context()`), so the dashboard preview, the PDF, and the emailed PDF can never disagree.
- `quotation_pdf_bytes()` / `invoice_pdf_bytes()` render PDFs via `xhtml2pdf`, with a
  `link_callback` so the company logo embeds correctly.

**booking/notifications.py**
- `send_quotation_email()` / `send_invoice_email()` — attach the generated PDF and email it,
  following the existing best-effort/logged pattern used by every other email in this module.

**booking/views.py** — new staff-only dashboard endpoints:
| Action | URL name |
|---|---|
| Preview quotation | `dashboard_quotation` |
| Download quotation PDF | `dashboard_quotation_pdf` |
| Generate/regenerate quotation + email | `dashboard_generate_quote` |
| Re-email quotation | `dashboard_email_quotation` |
| Preview invoice | `dashboard_invoice` (existing URL, rebuilt on `documents.py`) |
| Download invoice PDF | `dashboard_invoice_pdf` |
| Generate/regenerate invoice + email | `dashboard_generate_invoice` |
| Re-email invoice | `dashboard_email_invoice` |

**Templates**
- `templates/booking/documents/quotation_pdf.html`, `invoice_pdf.html`, `_pdf_styles.css` — the
  actual PDF layouts (table-based, since xhtml2pdf doesn't support flexbox/grid).
- `templates/booking/dashboard_quotation.html`, `dashboard_invoice.html` (rebuilt) — staff preview
  pages with Print / Download PDF / Generate / Email buttons.
- `admin_dashboard.html` and `dashboard_calendar.html` — added "Quote" / "Invoice" quick-action
  links per booking row.

**booking/admin.py**
- Added a read-only "Quotation" and "Invoice" fieldset to the booking detail page in Django
  Admin, each with a link into the preview/generate/download/email page above.

## Design notes
- **Document numbers** are `QUO-<year>-<booking id, zero-padded>` / `INV-<year>-<booking id>` —
  guaranteed unique since they're derived from the booking's own primary key, no separate
  sequence table needed.
- **Idempotent generation**: clicking "Generate" twice, or a booking receiving a second payment,
  never issues a second document number — it just refreshes the existing one's date/status.
- **Taxes**: `TAX_RATE` defaults to `0`, so every document shows "N/A" for tax until the business
  is VAT-registered and flips the constant.
- Every outbound quotation/invoice email is best-effort and logged, consistent with how the rest
  of `notifications.py` already handles a flaky mail server — a failed send never blocks a
  booking status change or a payment from being recorded.
