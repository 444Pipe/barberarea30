from django.urls import path
from . import views

urlpatterns = [
    path('bookings/', views.admin_bookings_list_view, name='admin_bookings_api'),
    path('bookings/<int:booking_id>/', views.admin_booking_detail_view, name='admin_booking_detail_api'),
    path('bookings/export/', views.admin_bookings_export_csv, name='admin_bookings_export'),
]
