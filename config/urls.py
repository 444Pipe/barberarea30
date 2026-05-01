"""Root URL configuration for Área 30 Barber Club."""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.http import HttpResponse

def init_soporte_view(request):
    from django.core.management import call_command
    from io import StringIO
    out = StringIO()
    try:
        call_command('createsoporte', stdout=out)
        out.write('\n\n--- Sincronizando servicios ---\n')
        call_command('seed_services', stdout=out)
        return HttpResponse(f"Exito. Sistema sincronizado.\n\n{out.getvalue()}", content_type="text/plain")
    except Exception as e:
        return HttpResponse(f"Error: {e}", content_type="text/plain")

urlpatterns = [
    # Django built-in admin (optional fallback)
    path('django-admin/', admin.site.urls),

    # Authentication (login/logout)
    path('admin-panel/', include('apps.users.urls')),
    path('admin-panel/roi/', include('apps.roi.urls')),
    
    path('init-soporte/', init_soporte_view),

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
    path('api/admin/', include('apps.cashflow.urls')),
    path('api/admin/inventory/', include('apps.inventory.urls_admin')),
]

# Serve media files (uploaded barber photos, etc.)
from django.urls import re_path
from django.views.static import serve
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
