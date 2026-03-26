"""Public page URLs."""
from django.urls import path
from django.views.generic import TemplateView

urlpatterns = [
    path('', TemplateView.as_view(template_name='public/index.html'), name='home'),
    path('services', TemplateView.as_view(template_name='public/services.html'), name='services'),
    path('gallery', TemplateView.as_view(template_name='public/gallery.html'), name='gallery'),
    path('booking', TemplateView.as_view(template_name='public/booking.html'), name='booking'),
    # Compatibilidad con rutas .html directas
    path('index.html', TemplateView.as_view(template_name='public/index.html')),
    path('services.html', TemplateView.as_view(template_name='public/services.html')),
    path('gallery.html', TemplateView.as_view(template_name='public/gallery.html')),
    path('booking.html', TemplateView.as_view(template_name='public/booking.html')),
]
