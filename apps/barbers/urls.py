from django.urls import path
from . import views

urlpatterns = [
    path('barbers/', views.BarberPublicListView.as_view(), name='barber_list'),
    path('barbers/<int:barber_id>/availability/',
         views.barber_availability_view, name='barber_availability'),
    path('barberos-nativos/', views.obtener_barberos_nativos, name='barberos_nativos'),
    path('gallery/', views.GalleryPublicListView.as_view(), name='gallery_list'),
]
