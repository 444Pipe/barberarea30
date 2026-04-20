from django.urls import path
from . import views

urlpatterns = [
    path('stats/dashboard/', views.dashboard_stats_view, name='admin_dashboard_stats'),
    path('stats/revenue/', views.revenue_stats_view, name='admin_revenue_stats'),
    path('stats/services/', views.services_stats_view, name='admin_services_stats'),
    path('stats/barbers/performance/', views.barber_performance_view, name='admin_barber_perf'),
    path('stats/heatmap/', views.heatmap_view, name='admin_heatmap'),
    path('notifications/', views.notifications_view, name='admin_notifications'),
    path('reports/monthly/', views.monthly_report_view, name='admin_monthly_report'),
]
