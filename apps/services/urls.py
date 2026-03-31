from django.urls import path
from . import views

urlpatterns = [
    path('services/', views.ServiceListView.as_view(), name='service_list'),
    path('servicios-nativos/', views.obtener_servicios_nativos, name='servicios_nativos'),
]
