from django.urls import path
from . import views

urlpatterns = [
    path('clients/', views.clients_list_view, name='admin_clients_api'),
    path('clients/<str:phone>/history/', views.client_history_view, name='admin_client_history'),
]
