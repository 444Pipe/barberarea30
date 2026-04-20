from django.urls import path
from . import views

urlpatterns = [
    path('checkout/<int:booking_id>/', views.checkout_booking_view, name='admin_checkout_api'),
]
