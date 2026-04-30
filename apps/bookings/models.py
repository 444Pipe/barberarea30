from django.db import models
from django.utils import timezone
from datetime import timedelta, datetime

from apps.barbers.models import Barber
from apps.services.models import Service


class Booking(models.Model):
    """Reserva de cita."""
    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('confirmed', 'Confirmado'),
        ('completed', 'Completado'),
        ('cancelled', 'Cancelado'),
    ]

    client_name = models.CharField(max_length=150)
    client_phone = models.CharField(max_length=20, blank=True)
    client_email = models.EmailField(blank=True)
    is_walk_in = models.BooleanField(default=False, 
        help_text='Cliente presencial sin reserva previa (ej. Cliente General)')
    privacy_accepted = models.BooleanField(default=False,
        help_text='Aceptación obligatoria de políticas de privacidad y tratamiento de datos')
    
    barber = models.ForeignKey(
        Barber, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='bookings',
        help_text='Puede quedar vacío inicialmente si eligen "Cualquier barbero"'
    )
    service = models.ForeignKey(
        Service, on_delete=models.SET_NULL,
        null=True, related_name='bookings'
    )
    date = models.DateField()
    time = models.TimeField()
    duration_minutes = models.IntegerField(default=60)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending'
    )
    notes = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=0)
    survey_sent = models.BooleanField(default=False)
    reminder_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Reserva'
        verbose_name_plural = 'Reservas'
        ordering = ['-date', '-time']

    def __str__(self):
        return f'{self.client_name} — {self.service} ({self.date} {self.time})'

    @property
    def can_cancel(self):
        """Se puede cancelar si la cita no ha empezado aún y no está completada ni cancelada."""
        if self.status in ['completed', 'cancelled']:
            return False
        
        # Combine date and time
        booking_datetime = timezone.make_aware(
            datetime.combine(self.date, self.time), 
            timezone.get_current_timezone()
        )
        # Allow cancellation up until the moment of the appointment
        return timezone.now() < booking_datetime


class Review(models.Model):
    """Calificación dual: Barbero y Local (Área 30)."""
    booking = models.OneToOneField(
        Booking, on_delete=models.CASCADE, related_name='review'
    )
    # Calificación 1 a 5
    barber_rating = models.PositiveSmallIntegerField(default=5)
    shop_rating = models.PositiveSmallIntegerField(default=5)
    comment = models.TextField(blank=True)
    is_public = models.BooleanField(default=False, 
        help_text='Determina si se muestra en el frontend (ej. solo >= 4 estrellas)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Reseña / Calificación'
        verbose_name_plural = 'Reseñas'
        ordering = ['-created_at']

    def __str__(self):
        return f'Review {self.booking.client_name} - Barbero: {self.barber_rating}, Local: {self.shop_rating}'

    def save(self, *args, **kwargs):
        # Auto-aprobar reseñas de 4 o más estrellas para el frontend público
        if self.barber_rating >= 4 and self.shop_rating >= 4:
            self.is_public = True
        super().save(*args, **kwargs)


class BlockedDate(models.Model):
    """Fechas en las que la barbería está cerrada o no disponible."""
    date = models.DateField(unique=True)
    start_time = models.TimeField(
        null=True, blank=True,
        help_text='Opcional. Si se define (junto con end_time), el día no estará completamente bloqueado, sino que se limitará a trabajar solo en este horario (ej: 10:00 a 14:00).'
    )
    end_time = models.TimeField(null=True, blank=True)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Fecha Bloqueada'
        verbose_name_plural = 'Fechas Bloqueadas'
        ordering = ['date']

    def __str__(self):
        return f'{self.date} — {self.description or "Bloqueado"}'


class Suggestion(models.Model):
    """Buzón de Sugerencias anónimo / público."""
    name = models.CharField(max_length=100, blank=True, help_text='Opcional')
    email = models.EmailField(blank=True, help_text='Opcional')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Sugerencia'
        verbose_name_plural = 'Buzón de Sugerencias'
        ordering = ['-created_at']

    def __str__(self):
        return f'Sugerencia de {self.name or "Anónimo"} - {self.created_at.strftime("%Y-%m-%d")}'
