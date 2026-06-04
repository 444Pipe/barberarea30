from django.urls import path
from . import views

urlpatterns = [
    path('', views.roi_dashboard_view, name='roi_dashboard'),
    path('generar-snapshot/', views.roi_generate_snapshot_view, name='roi_generate_snapshot'),
    path('bloquear/<int:snapshot_id>/', views.roi_lock_snapshot_view, name='roi_lock_snapshot'),
    path('limpiar/', views.roi_clean_snapshots_view, name='roi_clean_snapshots'),
    path('registrar-inversion/', views.roi_add_investment_view, name='roi_add_investment'),
    path('aportes/', views.roi_api_investments, name='roi_api_investments'),
    path('aportes/<int:investment_id>/editar/', views.roi_update_investment_view, name='roi_update_investment'),
    path('aportes/<int:investment_id>/eliminar/', views.roi_delete_investment_view, name='roi_delete_investment'),
    path('api/history/', views.roi_api_history, name='roi_api_history'),
]
