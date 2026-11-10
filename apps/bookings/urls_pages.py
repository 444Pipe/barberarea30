"""Public page URLs."""
from django.urls import path
from django.views.generic import TemplateView
from .views import HomeView, client_booking_detail_view, reservar_redirect_view

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path('services/', TemplateView.as_view(template_name='public/services.html'), name='services'),
    path('gallery/', TemplateView.as_view(template_name='public/gallery.html'), name='gallery'),
    # Página de reserva en una sola pantalla. También es el enlace directo
    # para Google / Instagram / WhatsApp (?servicio=..&barbero=..). /booking/
    # era el asistente de 4 pasos: sus enlaces viejos llegan aquí.
    path('reservar/', TemplateView.as_view(template_name='public/reservar.html'), name='reservar'),
    path('booking/', reservar_redirect_view, name='booking'),
    path('reserva/<str:signed_id>/', client_booking_detail_view, name='client_booking_detail'),
    path('politica-datos/', TemplateView.as_view(template_name='public/politica_datos.html'), name='politica_datos'),
    # Compatibilidad sin trailing slash
    path('services', TemplateView.as_view(template_name='public/services.html')),
    path('gallery', TemplateView.as_view(template_name='public/gallery.html')),
    path('reservar', reservar_redirect_view),
    path('booking', reservar_redirect_view),
    # Compatibilidad con rutas .html directas
    path('index.html', TemplateView.as_view(template_name='public/index.html')),
    path('services.html', TemplateView.as_view(template_name='public/services.html')),
    path('gallery.html', TemplateView.as_view(template_name='public/gallery.html')),
    path('booking.html', reservar_redirect_view),
    path('rate/<str:token>/', TemplateView.as_view(template_name='public/rate.html'), name='rate_booking'),
    path('reels/', TemplateView.as_view(template_name='public/reels.html'), name='reels'),
    path('reels', TemplateView.as_view(template_name='public/reels.html')),
    path('profesionales/', TemplateView.as_view(template_name='public/profesionales.html'), name='profesionales'),
    path('profesionales', TemplateView.as_view(template_name='public/profesionales.html')),
]
