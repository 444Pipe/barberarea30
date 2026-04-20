from django.urls import path
from . import views

urlpatterns = [
    path('<int:item_id>/adjust/', views.adjust_inventory_view, name='admin_inventory_adjust_api'),
]
