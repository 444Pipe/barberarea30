from django.urls import path
from . import views

urlpatterns = [
    path('checkout/<int:booking_id>/', views.checkout_booking_view, name='admin_checkout_api'),
    path('cashflow/daily-close/', views.daily_close_view, name='admin_daily_close_api'),
    path('cashflow/daily-close/<int:close_id>/detail/', views.daily_close_detail_view, name='admin_daily_close_detail_api'),
    path('cashflow/expenses/', views.add_expense_view, name='admin_add_expense_api'),
    path('cashflow/expenses/<int:expense_id>/delete/', views.delete_expense_view, name='admin_delete_expense_api'),

    # ── Rutas con prefijo cashflow/ (usadas por el frontend) ──────────────
    path('cashflow/pending-approvals/', views.pending_approvals_view, name='cashflow_pending_approvals_api'),
    path('cashflow/sales/<int:sale_id>/approve/', views.approve_sale_view, name='cashflow_approve_sale_api'),
    path('cashflow/sales/<int:sale_id>/reject/', views.reject_sale_view, name='cashflow_reject_sale_api'),

    # ── Alias sin prefijo (compatibilidad hacia atrás) ────────────────────
    path('sales/pending/', views.pending_approvals_view, name='pending_sales_list_api'),
    path('sales/<int:sale_id>/approve/', views.approve_sale_view, name='approve_sale_api'),
    path('sales/<int:sale_id>/reject/', views.reject_sale_view, name='reject_sale_api'),
]
