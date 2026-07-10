from django.urls import path
from . import views

urlpatterns = [
    path('bookings/', views.create_booking_view, name='create_booking'),
    path('bookings/<str:signed_id>/cancel/', views.cancel_booking_view, name='cancel_booking'),
    path('bookings/<str:signed_id>/review/', views.add_review_view, name='add_booking_review'),
    path('blocked-dates/', views.public_blocked_dates_list, name='blocked_dates_list'),
    path('suggestions/', views.add_suggestion_view, name='add_suggestion'),
    path('reviews/', views.public_reviews_view, name='public_reviews'),
]
