from django.urls import path
from . import views

urlpatterns = [
    path('bookings/', views.admin_bookings_list_view, name='admin_bookings_api'),
    path('bookings/bulk-delete/', views.admin_delete_all_bookings_view, name='admin_bookings_bulk_delete'),
    path('bookings/<int:booking_id>/', views.admin_booking_detail_view, name='admin_booking_detail_api'),
    path('bookings/export/', views.admin_bookings_export_csv, name='admin_bookings_export'),
    path('blocked-dates/', views.admin_blocked_dates_view, name='admin_blocked_dates_api'),
    path('blocked-dates/<int:pk>/', views.admin_blocked_date_detail_view, name='admin_blocked_date_detail_api'),
    path('reviews/<int:pk>/', views.admin_delete_review_view, name='admin_delete_review'),
]
