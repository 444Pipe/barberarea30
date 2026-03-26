from django.urls import path
from . import views

urlpatterns = [
    path('bookings/', views.create_booking_view, name='create_booking'),
]
