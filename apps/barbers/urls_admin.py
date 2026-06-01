from django.urls import path
from . import views

urlpatterns = [
    path('barbers/', views.BarberAdminListCreateView.as_view(), name='admin_barber_list'),
    path('barbers/<int:pk>/', views.BarberAdminDetailView.as_view(), name='admin_barber_detail'),
    path('barbers/<int:barber_id>/stats/', views.barber_stats_view, name='admin_barber_stats'),
    path('barbers/<int:barber_id>/unavailability/', views.barber_unavailability_list, name='admin_barber_unavailability_list'),
    path('barbers/<int:barber_id>/unavailability/bulk/', views.barber_unavailability_bulk_create, name='admin_barber_unavailability_bulk'),
    path('barbers/<int:barber_id>/unavailability/<int:unavail_id>/', views.barber_unavailability_delete, name='admin_barber_unavailability_delete'),
    path('gallery/', views.GalleryAdminListCreateView.as_view(), name='admin_gallery_list'),
    path('gallery/<int:pk>/', views.GalleryAdminDetailView.as_view(), name='admin_gallery_detail'),
    path('reels/', views.ReelAdminListCreateView.as_view(), name='admin_reel_list'),
    path('reels/<int:pk>/', views.ReelAdminDetailView.as_view(), name='admin_reel_detail'),
]
