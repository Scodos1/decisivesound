"""
Quotation & invoice document generation.

This module is the single source of truth for what goes on a quotation
or invoice - both the browser preview pages (dashboard_quotation.html /
dashboard_invoice.html) and the emailed/downloaded PDFs are built from
the *_context() functions below, so the numbers a staff member previews
can never drift from what actually gets sent to the customer.

PDFs are rendered with xhtml2pdf (ReportLab-backed). Its CSS support is
limited - no flexbox/grid, no @media queries - so the PDF templates
(templates/booking/documents/*_pdf.html) use plain table/block layout.
The nicer-looking dashboard preview pages are free to use modern CSS
since browsers render those directly.
"""
import logging
from io import BytesIO

from django.contrib.staticfiles import finders
from django.template.loader import render_to_string

from .models import CAUTION_FEE, RATE_PER_HEADSET, SERVICE_CHARGE, TAX_RATE

logger = logging.getLogger(__name__)

COMPANY_NAME = "Decisive Sound NG"
COMPANY_TAGLINE = "Silent Disco & Event Sound Rentals"
COMPANY_EMAIL = "decisivesound8@gmail.com"

PAYMENT_INSTRUCTIONS = (
    "Payment can be made online via the secure payment link included in "
    "your booking emails, or by bank transfer - contact us on WhatsApp "
    "for account details. The caution fee is refundable after the event, "
    "subject to equipment being returned undamaged."
)


def _document_context(booking):
    """Shared pricing/booking context for both quotations and invoices -
    everything in the spec's "Quotation Contents" list, plus the extra
    invoice-only fields layered on top by invoice_context()."""
    is_lagos = booking.state == "Lagos"
    rental = booking.headsets * RATE_PER_HEADSET
    service_charge = SERVICE_CHARGE if is_lagos else None

    subtotal = tax_amount = total = outstanding_balance = None
    if is_lagos:
        subtotal = rental + service_charge + CAUTION_FEE
        tax_amount = round(subtotal * TAX_RATE) if TAX_RATE else 0
        total = subtotal + tax_amount
        outstanding_balance = max(total - booking.amount_paid, 0)

    return {
        "booking": booking,
        "company_name": COMPANY_NAME,
        "company_tagline": COMPANY_TAGLINE,
        "company_email": COMPANY_EMAIL,
        "payment_instructions": PAYMENT_INSTRUCTIONS,
        "rate_per_headset": RATE_PER_HEADSET,
        "rental": rental,
        "service_charge": service_charge,
        "caution_fee": CAUTION_FEE,
        "tax_rate": TAX_RATE,
        "tax_amount": tax_amount,
        "subtotal": subtotal,
        "total": total,
        "outstanding_balance": outstanding_balance,
        "is_lagos": is_lagos,
    }


def quotation_context(booking):
    return _document_context(booking)


def invoice_context(booking):
    context = _document_context(booking)
    context["booking_status"] = booking.status
    return context


def _link_callback(uri, rel):
    """Resolves {% static %} URLs to filesystem paths so xhtml2pdf can
    embed images (the company logo) in the generated PDF - it can't
    fetch them over HTTP the way a browser would."""
    result = finders.find(uri.replace("/static/", "", 1)) if "/static/" in uri else None
    return result or uri


def _render_pdf(template_name, context):
    html = render_to_string(template_name, context)
    buffer = BytesIO()
    try:
        from xhtml2pdf import pisa
    except ImportError:
        logger.error("xhtml2pdf is not installed - cannot render %s", template_name)
        return None
    result = pisa.CreatePDF(src=html, dest=buffer, link_callback=_link_callback)
    if result.err:
        logger.error("PDF generation failed for template %s", template_name)
        return None
    return buffer.getvalue()


def render_pdf(template_name, context):
    """Public entry point for other modules (e.g. reports.py) that need
    to render an arbitrary HTML template to PDF bytes via xhtml2pdf,
    without reaching into the underscore-prefixed helper above."""
    return _render_pdf(template_name, context)


def quotation_pdf_bytes(booking):
    return _render_pdf("booking/documents/quotation_pdf.html", quotation_context(booking))


def invoice_pdf_bytes(booking):
    return _render_pdf("booking/documents/invoice_pdf.html", invoice_context(booking))
