from django.urls import path
from . import views

urlpatterns = [
    # Ajuste de stock (existente)
    path('<int:item_id>/adjust/', views.adjust_inventory_view, name='admin_inventory_adjust_api'),
    # CRUD de productos
    path('items/', views.inventory_list_view, name='admin_inventory_list_api'),
    path('items/create/', views.inventory_create_view, name='admin_inventory_create_api'),
    path('items/<int:item_id>/update/', views.inventory_update_view, name='admin_inventory_update_api'),
    path('items/<int:item_id>/delete/', views.inventory_delete_view, name='admin_inventory_delete_api'),
    # Consumibles para checkout del barbero
    path('consumables/', views.consumables_for_checkout_view, name='admin_inventory_consumables'),
    path('consumables/<int:booking_id>/', views.register_consumables_view, name='admin_inventory_register_consumables'),
]
