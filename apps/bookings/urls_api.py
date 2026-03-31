from django.urls import path
from . import views

urlpatterns = [
    path('bookings/', views.create_booking_view, name='create_booking'),
    path('blocked-dates/', views.public_blocked_dates_list, name='blocked_dates_list'),
]
