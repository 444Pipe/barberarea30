from django.urls import path
from . import views

urlpatterns = [
    path('', views.roi_dashboard_view, name='roi_dashboard'),
    path('generar-snapshot/', views.roi_generate_snapshot_view, name='roi_generate_snapshot'),
    path('bloquear/<int:snapshot_id>/', views.roi_lock_snapshot_view, name='roi_lock_snapshot'),
    path('api/history/', views.roi_api_history, name='roi_api_history'),
]
