"""Root URL configuration for Área 30 Barber Club."""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include

urlpatterns = [
    # Django built-in admin (optional fallback)
    path('django-admin/', admin.site.urls),

    # Authentication (login/logout)
    path('admin-panel/', include('apps.users.urls')),

    # Public pages
    path('', include('apps.bookings.urls_pages')),
    path('barbero/', include('apps.barbers.urls_pages')),

    # Public API
    path('api/', include('apps.services.urls')),
    path('api/', include('apps.barbers.urls')),
    path('api/', include('apps.bookings.urls_api')),

    # Admin API
    path('api/admin/', include('apps.bookings.urls_admin_api')),
    path('api/admin/', include('apps.barbers.urls_admin')),
    path('api/admin/', include('apps.clients.urls')),
    path('api/admin/', include('apps.analytics.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
