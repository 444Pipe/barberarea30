from django.urls import path
from . import views

urlpatterns = [
    path('checkout/<int:booking_id>/', views.checkout_booking_view, name='admin_checkout_api'),
    path('cashflow/daily-close/', views.daily_close_view, name='admin_daily_close_api'),
    path('cashflow/expenses/', views.add_expense_view, name='admin_add_expense_api'),
]
