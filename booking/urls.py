from django.contrib.auth import views as auth_views
from django.urls import path

from . import portal_views
from . import views
from .forms import CustomerAuthenticationForm

urlpatterns = [
    # Customer Portal (auth + dashboard)
    path("portal/register/", portal_views.register, name="portal_register"),
    path(
        "portal/login/",
        auth_views.LoginView.as_view(
            template_name="booking/portal/login.html",
            authentication_form=CustomerAuthenticationForm,
        ),
        name="portal_login",
    ),
    path(
        "portal/logout/",
        auth_views.LogoutView.as_view(next_page="portal_login"),
        name="portal_logout",
    ),
    path(
        "portal/password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="booking/portal/password_reset.html",
            email_template_name="booking/portal/password_reset_email.txt",
            subject_template_name="booking/portal/password_reset_subject.txt",
            success_url="/portal/password-reset/done/",
        ),
        name="portal_password_reset",
    ),
    path(
        "portal/password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="booking/portal/password_reset_done.html",
        ),
        name="portal_password_reset_done",
    ),
    path(
        "portal/password-reset/confirm/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="booking/portal/password_reset_confirm.html",
            success_url="/portal/password-reset/complete/",
        ),
        name="portal_password_reset_confirm",
    ),
    path(
        "portal/password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="booking/portal/password_reset_complete.html",
        ),
        name="portal_password_reset_complete",
    ),
    path("portal/dashboard/", portal_views.dashboard, name="portal_dashboard"),
    path("portal/notifications/read/", portal_views.mark_notifications_read, name="portal_mark_notifications_read"),
    path("portal/booking/<int:booking_id>/", portal_views.booking_detail, name="portal_booking_detail"),
    path("portal/booking/<int:booking_id>/quotation.pdf", portal_views.quotation_pdf, name="portal_quotation_pdf"),
    path("portal/booking/<int:booking_id>/invoice.pdf", portal_views.invoice_pdf, name="portal_invoice_pdf"),
    path("portal/booking/<int:booking_id>/request-cancellation/", portal_views.request_cancellation, name="portal_request_cancellation"),
    path("portal/profile/", portal_views.profile, name="portal_profile"),

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