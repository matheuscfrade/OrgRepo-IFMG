from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]

# Development always serves media. Production serves media only when SERVE_MEDIA=True
# (default for Docker volume go-live; set False if a reverse proxy serves /media/).
_serve_media = settings.DEBUG or getattr(settings, "SERVE_MEDIA", False)
if _serve_media and settings.MEDIA_URL and settings.MEDIA_ROOT:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
