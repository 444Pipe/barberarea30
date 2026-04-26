from django.urls import path
from . import views
from . import views_approval
from . import views_pending

urlpatterns = [
    path('checkout/<int:booking_id>/', views.checkout_booking_view, name='admin_checkout_api'),
    path('cashflow/daily-close/', views.daily_close_view, name='admin_daily_close_api'),
    path('cashflow/expenses/', views.add_expense_view, name='admin_add_expense_api'),
    path('sales/<int:sale_id>/approve/', views_approval.approve_sale, name='approve_sale_api'),
    path('sales/<int:sale_id>/reject/', views_approval.reject_sale, name='reject_sale_api'),
    path('sales/pending/', views_pending.pending_sales_list, name='pending_sales_list_api'),
]
