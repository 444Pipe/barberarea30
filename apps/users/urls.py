from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views

urlpatterns = [
    # Auth pages
    path('login/', views.admin_login_view, name='admin_login'),
    path('logout/', views.admin_logout_view, name='admin_logout'),

    # JWT API tokens
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Admin panel pages
    path('', views.admin_dashboard_view, name='admin_dashboard'),
    path('calendar/', views.admin_calendar_view, name='admin_calendar'),
    path('bookings/', views.admin_bookings_view, name='admin_bookings'),
    path('mis-reservas/', views.admin_mis_reservas_view, name='admin_mis_reservas'),
    path('barbers/', views.admin_barbers_view, name='admin_barbers'),
    path('barbers/my-agenda/', views.admin_barber_agenda_view, name='admin_barber_agenda'),
    path('clients/', views.admin_clients_view, name='admin_clients'),
    path('charts/', views.admin_charts_view, name='admin_charts'),
    path('settings/', views.admin_settings_view, name='admin_settings'),
    path('gallery/', views.admin_gallery_view, name='admin_gallery'),
    path('reels/', views.admin_reels_view, name='admin_reels'),
    path('cashflow/', views.admin_cashflow_view, name='admin_cashflow'),
    path('expenses/', views.admin_expenses_view, name='admin_expenses'),
    path('inventory/', views.admin_inventory_view, name='admin_inventory'),
    path('reports/', views.admin_reports_view, name='admin_reports'),
    path('audit-log/', views.admin_audit_log_view, name='admin_audit_log'),
    path('reviews/', views.admin_reviews_view, name='admin_reviews'),
    path('manual-service/', views.admin_manual_service_view, name='admin_manual_service'),
]
