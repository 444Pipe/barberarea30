from django.db import models
from django.contrib.auth.models import User

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
