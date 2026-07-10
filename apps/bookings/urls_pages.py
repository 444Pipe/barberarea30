"""Public page URLs."""
from django.urls import path
from django.views.generic import TemplateView
from .views import HomeView, client_booking_detail_view

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path('services/', TemplateView.as_view(template_name='public/services.html'), name='services'),
    path('gallery/', TemplateView.as_view(template_name='public/gallery.html'), name='gallery'),
    path('booking/', TemplateView.as_view(template_name='public/booking.html'), name='booking'),
    path('reserva/<str:signed_id>/', client_booking_detail_view, name='client_booking_detail'),
    path('politica-datos/', TemplateView.as_view(template_name='public/politica_datos.html'), name='politica_datos'),
    # Compatibilidad sin trailing slash
    path('services', TemplateView.as_view(template_name='public/services.html')),
    path('gallery', TemplateView.as_view(template_name='public/gallery.html')),
    path('booking', TemplateView.as_view(template_name='public/booking.html')),
    # Compatibilidad con rutas .html directas
    path('index.html', TemplateView.as_view(template_name='public/index.html')),
    path('services.html', TemplateView.as_view(template_name='public/services.html')),
    path('gallery.html', TemplateView.as_view(template_name='public/gallery.html')),
    path('booking.html', TemplateView.as_view(template_name='public/booking.html')),
    path('rate/<str:token>/', TemplateView.as_view(template_name='public/rate.html'), name='rate_booking'),
    path('reels/', TemplateView.as_view(template_name='public/reels.html'), name='reels'),
    path('reels', TemplateView.as_view(template_name='public/reels.html')),
    path('profesionales/', TemplateView.as_view(template_name='public/profesionales.html'), name='profesionales'),
    path('profesionales', TemplateView.as_view(template_name='public/profesionales.html')),
]
