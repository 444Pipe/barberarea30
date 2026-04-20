from django.db import models
from django.contrib.auth.models import User

from apps.users.models import Barbershop
from apps.services.models import Service


class Barber(models.Model):
    """Perfil de barbero con horario y especialidades."""
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='barber_profile'
    )
    barbershop = models.ForeignKey(
        Barbershop, on_delete=models.CASCADE, related_name='barbers'
    )
    display_name = models.CharField(max_length=100)
    specialties = models.ManyToManyField(Service, blank=True, related_name='specialist_barbers')
    avatar = models.ImageField(upload_to='barbers/', null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    bio = models.TextField(blank=True)
    is_available = models.BooleanField(default=True)
    # Weekly schedule: {"monday": {"start": "09:00", "end": "20:00"}, ...}
    # Use null for days off
    schedule = models.JSONField(default=dict, blank=True)
    color_tag = models.CharField(
        max_length=7, default='#D4AF37',
        help_text='Color hexadecimal para el calendario'
    )
    total_cuts = models.IntegerField(default=0)
    rating = models.DecimalField(max_digits=2, decimal_places=1, default=5.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Barbero'
        verbose_name_plural = 'Barberos'

    def __str__(self):
        return self.display_name

    def get_default_schedule(self):
        """Devuelve horario por defecto (Lun-Sáb 09–20, Dom 09–14)."""
        return {
            'monday': {'start': '09:00', 'end': '20:00'},
            'tuesday': {'start': '09:00', 'end': '20:00'},
            'wednesday': {'start': '09:00', 'end': '20:00'},
            'thursday': {'start': '09:00', 'end': '20:00'},
            'friday': {'start': '09:00', 'end': '20:00'},
            'saturday': {'start': '09:00', 'end': '20:00'},
            'sunday': {'start': '09:00', 'end': '14:00'},
        }

    def save(self, *args, **kwargs):
        if not self.schedule:
            self.schedule = self.get_default_schedule()
        super().save(*args, **kwargs)


class GalleryImage(models.Model):
    """Imagen de galería — trabajos realizados."""
    image = models.ImageField(upload_to='gallery/')
    title = models.CharField(max_length=150, blank=True)
    barber = models.ForeignKey(
        Barber, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='gallery_images'
    )
    display_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Imagen de Galería'
        verbose_name_plural = 'Imágenes de Galería'
        ordering = ['-created_at']

    def __str__(self):
        return self.title or f'Imagen #{self.pk}'


class Reel(models.Model):
    """Video estilo reel — trabajos en video para la página pública."""
    video = models.FileField(upload_to='reels/', help_text='Video MP4 vertical (9:16 recomendado)')
    thumbnail = models.ImageField(upload_to='reels/thumbs/', null=True, blank=True,
        help_text='Miniatura opcional. Si no se sube se usa el primer frame del video.')
    title = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    barber = models.ForeignKey(
        Barber, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reels'
    )
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Reel'
        verbose_name_plural = 'Reels'
        ordering = ['display_order', '-created_at']

    def __str__(self):
        return self.title or f'Reel #{self.pk}'
