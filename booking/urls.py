from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("services/", views.services, name="services"),
    path("gallery/", views.gallery, name="gallery"),
    path("equipment/", views.equipment, name="equipment"),
    path("contact/", views.contact, name="contact"),
    path("booking/", views.booking, name="booking"),
    path("booking/success/<int:booking_id>/", views.booking_success, name="booking_success"),
    path("dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("dashboard/booking/<int:booking_id>/action/", views.dashboard_booking_action, name="dashboard_booking_action"),
    path("dashboard/calendar/", views.dashboard_calendar, name="dashboard_calendar"),
    path("dashboard/invoice/<int:booking_id>/", views.dashboard_invoice, name="dashboard_invoice"),
    path("dashboard/invoice/<int:booking_id>/pdf/", views.dashboard_invoice_pdf, name="dashboard_invoice_pdf"),
    path("dashboard/invoice/<int:booking_id>/generate/", views.dashboard_generate_invoice, name="dashboard_generate_invoice"),
    path("dashboard/invoice/<int:booking_id>/email/", views.dashboard_email_invoice, name="dashboard_email_invoice"),
    path("dashboard/quotation/<int:booking_id>/", views.dashboard_quotation, name="dashboard_quotation"),
    path("dashboard/quotation/<int:booking_id>/pdf/", views.dashboard_quotation_pdf, name="dashboard_quotation_pdf"),
    path("dashboard/quotation/<int:booking_id>/generate/", views.dashboard_generate_quote, name="dashboard_generate_quote"),
    path("dashboard/quotation/<int:booking_id>/email/", views.dashboard_email_quotation, name="dashboard_email_quotation"),
    path("dashboard/report/", views.dashboard_report, name="dashboard_report"),
    path("dashboard/analytics/", views.analytics_dashboard, name="analytics_dashboard"),
    path("dashboard/analytics/data/", views.analytics_data, name="analytics_data"),
    path("dashboard/analytics/report/", views.analytics_report, name="analytics_report"),
    path("dashboard/email/", views.dashboard_send_email, name="dashboard_send_email"),
    path("terms/", views.terms, name="terms"),

    # Payments (Paystack) — see booking/views.py "Payments" section.
    path("payment/<int:booking_id>/", views.payment_page, name="payment_page"),
    path("payment/<int:booking_id>/initiate/", views.payment_initiate, name="payment_initiate"),
    path("payment/callback/", views.payment_callback, name="payment_callback"),
    path("payment/success/<int:booking_id>/", views.payment_success, name="payment_success"),
    path("payment/webhook/", views.payment_webhook, name="payment_webhook"),
]