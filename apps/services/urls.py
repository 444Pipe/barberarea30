from django.urls import path
from . import views

urlpatterns = [
    path('services/', views.ServiceListView.as_view(), name='service_list'),
    path('services/<int:pk>/', views.ServiceDetailView.as_view(), name='service_detail'),
    path('servicios-nativos/', views.obtener_servicios_nativos, name='servicios_nativos'),
]
