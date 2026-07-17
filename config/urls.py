from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]

# Development always serves media. Production serves media only when SERVE_MEDIA=True
# (default for Docker volume go-live; set False if a reverse proxy serves /media/).
#
# IMPORTANT: django.conf.urls.static.static() is a no-op when DEBUG=False.
# We register an explicit serve view so SERVE_MEDIA works under Gunicorn.
_serve_media = settings.DEBUG or getattr(settings, "SERVE_MEDIA", False)
if _serve_media and settings.MEDIA_URL and settings.MEDIA_ROOT:
    media_url = settings.MEDIA_URL.lstrip("/")
    urlpatterns += [
        re_path(
            rf"^{media_url}(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
