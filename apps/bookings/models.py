from django.db import models

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
    client_phone = models.CharField(max_length=20)
    client_email = models.EmailField(blank=True)
    barber = models.ForeignKey(
        Barber, on_delete=models.SET_NULL,
        null=True, related_name='bookings'
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Reserva'
        verbose_name_plural = 'Reservas'
        ordering = ['-date', '-time']

    def __str__(self):
        return f'{self.client_name} — {self.service} ({self.date} {self.time})'


class BlockedDate(models.Model):
    """Fechas en las que la barbería está cerrada o no disponible."""
    date = models.DateField(unique=True)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Fecha Bloqueada'
        verbose_name_plural = 'Fechas Bloqueadas'
        ordering = ['date']

    def __str__(self):
        return f'{self.date} — {self.description or "Bloqueado"}'
