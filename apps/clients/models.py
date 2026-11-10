from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class MembershipTier(models.Model):
    name = models.CharField(max_length=50) # Silver, Gold, Diamond
    discount_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, help_text="Ej: 10% de descuento en servicios (usar 10.00)"
    )
    monthly_price = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    free_drinks_per_month = models.IntegerField(
        default=0, help_text="Cantidad de bebidas gratis al mes (ej: 2 cervezas)"
    )

    class Meta:
        verbose_name = 'Nivel de Membresía'
        verbose_name_plural = 'Niveles de Membresía'

    def __str__(self):
        return self.name


class Client(models.Model):
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True)
    phone = models.CharField(max_length=20, unique=True, db_index=True)
    full_name = models.CharField(max_length=150)
    
    # Membresía
    membership = models.ForeignKey(MembershipTier, on_delete=models.SET_NULL, null=True, blank=True)
    membership_active_until = models.DateField(null=True, blank=True)
    
    # Legal y Habeas Data
    habeas_data_accepted = models.BooleanField(
        default=False, help_text="True si aceptó política de tratamiento de datos al agendar/registrarse"
    )
    habeas_data_date = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'

    def __str__(self):
        return f"{self.full_name} ({self.phone})"


# ── Tarjeta de sellos (prueba, nov-2026) ─────────────────────────────────
# Por ahora solo existe en el panel: el cliente no ve nada todavía.
# Los sellos NO se guardan: se calculan desde las ventas aprobadas en caja
# (apps/clients/loyalty.py). Aquí solo viven las reglas y los canjes.

class LoyaltySettings(models.Model):
    """Reglas de la tarjeta de sellos. Una sola fila (pk=1); la edita un superadmin."""
    stamps_required = models.PositiveSmallIntegerField(
        default=10, help_text='Sellos para ganar el premio')
    min_service_price = models.DecimalField(
        max_digits=10, decimal_places=0, default=30000,
        help_text='Solo suman sello los servicios con precio desde este valor')
    expiry_months = models.PositiveSmallIntegerField(
        default=6, help_text='Meses que dura cada sello (0 = no vencen)')
    reward_service = models.ForeignKey(
        'services.Service', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', help_text='Servicio que se regala al completar la tarjeta')
    reward_note = models.CharField(
        max_length=200, blank=True, help_text='Aclaración del premio (opcional)')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = 'Reglas de la tarjeta de sellos'
        verbose_name_plural = 'Reglas de la tarjeta de sellos'

    def __str__(self):
        return f'Tarjeta de {self.stamps_required} sellos'

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class LoyaltyRedemption(models.Model):
    """Canje de una tarjeta llena. Gasta los sellos vigentes más antiguos."""
    phone = models.CharField(
        max_length=20, db_index=True,
        help_text='Celular del cliente normalizado (solo dígitos, sin 57)')
    client_name = models.CharField(max_length=150, blank=True)
    stamps_used = models.PositiveSmallIntegerField()
    reward_service = models.ForeignKey(
        'services.Service', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    notes = models.CharField(max_length=200, blank=True)
    redeemed_at = models.DateTimeField(default=timezone.now)
    redeemed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['-redeemed_at', '-id']
        verbose_name = 'Canje de tarjeta de sellos'
        verbose_name_plural = 'Canjes de tarjeta de sellos'

    def __str__(self):
        return f'{self.client_name or self.phone} — {self.redeemed_at:%Y-%m-%d}'
