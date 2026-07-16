from django.urls import path
from . import views

urlpatterns = [
    path('checkout/<int:booking_id>/', views.checkout_booking_view, name='admin_checkout_api'),
    path('cashflow/daily-close/', views.daily_close_view, name='admin_daily_close_api'),
    path('cashflow/daily-close/preview/', views.daily_close_preview_view, name='admin_daily_close_preview_api'),
    path('cashflow/daily-closes/', views.daily_closes_list_view, name='admin_daily_closes_list_api'),
    path('cashflow/daily-close/<int:close_id>/detail/', views.daily_close_detail_view, name='admin_daily_close_detail_api'),
    path('cashflow/daily-close/<int:close_id>/delete/', views.delete_daily_close_view, name='admin_delete_daily_close_api'),
    path('cashflow/live-detail/', views.live_cashflow_detail_view, name='admin_live_cashflow_detail_api'),
    path('cashflow/expenses/', views.add_expense_view, name='admin_add_expense_api'),
    path('cashflow/fix-frank-history/', views.fix_frank_history_view, name='admin_fix_frank_history_api'),
    path('cashflow/expenses/<int:expense_id>/delete/', views.delete_expense_view, name='admin_delete_expense_api'),
    path('cashflow/expenses/<int:expense_id>/edit/', views.edit_expense_view, name='admin_edit_expense_api'),

    # ── Rutas con prefijo cashflow/ (usadas por el frontend) ──────────────
    path('cashflow/barber-payments/', views.unpaid_commissions_view, name='cashflow_barber_payments_api'),
    path('cashflow/barber-payments/<int:barber_id>/pay/', views.pay_barber_view, name='cashflow_pay_barber_api'),
    path('cashflow/barber-payments/<int:barber_id>/detail/', views.barber_payment_detail_view, name='cashflow_barber_payment_detail_api'),
    path('cashflow/barber-payments/<int:barber_id>/advance/', views.register_barber_advance_view, name='cashflow_barber_advance_api'),
    path('cashflow/barber-payments/advance/<int:advance_id>/', views.delete_barber_advance_view, name='cashflow_delete_barber_advance_api'),
    path('cashflow/barber-payments/payment/<int:payment_id>/delete/', views.delete_barber_payment_view, name='cashflow_delete_barber_payment_api'),
    path('cashflow/inventory-sales/', views.create_inventory_sale_view, name='cashflow_inventory_sales_api'),
    path('cashflow/pending-approvals/', views.pending_approvals_view, name='cashflow_pending_approvals_api'),
    path('cashflow/alerts/', views.cashflow_alerts_view, name='cashflow_alerts_api'),
    path('cashflow/sales/<int:sale_id>/approve/', views.approve_sale_view, name='cashflow_approve_sale_api'),
    path('cashflow/sales/<int:sale_id>/reject/', views.reject_sale_view, name='cashflow_reject_sale_api'),
    path('cashflow/sales/<int:sale_id>/edit-payment/', views.edit_sale_payment_method_view, name='cashflow_edit_sale_payment_api'),
    path('cashflow/inventory-sales/<int:sale_id>/edit-payment/', views.edit_inventory_sale_payment_method_view, name='cashflow_edit_inv_sale_payment_api'),

    # ── Alias sin prefijo (compatibilidad hacia atrás) ────────────────────
    path('sales/pending/', views.pending_approvals_view, name='pending_sales_list_api'),
    path('sales/<int:sale_id>/approve/', views.approve_sale_view, name='approve_sale_api'),
    path('sales/<int:sale_id>/reject/', views.reject_sale_view, name='reject_sale_api'),
]
