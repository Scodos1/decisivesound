from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("booking.urls")),
]

if settings.DEBUG:
    # Local development only - production should have its web server (or
    # object storage / CDN) serve MEDIA_URL directly instead of Django.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)