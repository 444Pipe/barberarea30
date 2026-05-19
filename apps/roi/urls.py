from django.urls import path
from . import views

urlpatterns = [
    path('', views.roi_dashboard_view, name='roi_dashboard'),
    path('generar-snapshot/', views.roi_generate_snapshot_view, name='roi_generate_snapshot'),
    path('bloquear/<int:snapshot_id>/', views.roi_lock_snapshot_view, name='roi_lock_snapshot'),
    path('limpiar/', views.roi_clean_snapshots_view, name='roi_clean_snapshots'),
    path('registrar-inversion/', views.roi_add_investment_view, name='roi_add_investment'),
    path('api/history/', views.roi_api_history, name='roi_api_history'),
]
