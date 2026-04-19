from django.db import models
from django.contrib.auth.models import User


class InventoryItem(models.Model):
    """Producto en inventario (bebidas, insumos de servicios, etc.)."""
    CATEGORY_CHOICES = [
        ('beverage', 'Bebida'),
        ('hair_product', 'Producto Capilar'),
        ('consumable', 'Consumible'),
        ('other', 'Otro'),
    ]

    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=50, default='unidad',
        help_text='Ej: unidad, botella, litro, gramo')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    minimum_stock = models.DecimalField(max_digits=10, decimal_places=2, default=5,
        help_text='Nivel mínimo; se genera alerta si quantity <= minimum_stock')
    cost_per_unit = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Producto de Inventario'
        verbose_name_plural = 'Inventario'
        ordering = ['category', 'name']

    def __str__(self):
        return f'{self.name} ({self.quantity} {self.unit})'

    @property
    def is_low_stock(self):
        return self.quantity <= self.minimum_stock


class ServiceInventoryItem(models.Model):
    """Relación de cuántas unidades de un producto consume un servicio."""
    service = models.ForeignKey(
        'services.Service', on_delete=models.CASCADE,
        related_name='inventory_requirements'
    )
    item = models.ForeignKey(
        InventoryItem, on_delete=models.CASCADE,
        related_name='service_usages'
    )
    quantity_per_service = models.DecimalField(max_digits=6, decimal_places=2, default=1)

    class Meta:
        verbose_name = 'Consumo de Inventario por Servicio'
        verbose_name_plural = 'Consumos de Inventario por Servicio'
        unique_together = ('service', 'item')

    def __str__(self):
        return f'{self.service.name} → {self.quantity_per_service} {self.item.unit} de {self.item.name}'


class InventoryMovement(models.Model):
    """Registro de cada entrada o salida de inventario."""
    MOVEMENT_TYPES = [
        ('in', 'Entrada'),
        ('out', 'Salida por Servicio'),
        ('adjustment', 'Ajuste Manual'),
        ('purchase', 'Compra'),
        ('waste', 'Desperdicio / Merma'),
    ]

    item = models.ForeignKey(
        InventoryItem, on_delete=models.CASCADE,
        related_name='movements'
    )
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    quantity_before = models.DecimalField(max_digits=10, decimal_places=2)
    quantity_after = models.DecimalField(max_digits=10, decimal_places=2)
    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='inventory_movements'
    )
    performed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inventory_movements'
    )
    notes = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Movimiento de Inventario'
        verbose_name_plural = 'Movimientos de Inventario'
        ordering = ['-created_at']

    def __str__(self):
        sign = '+' if self.movement_type in ('in', 'purchase') else '-'
        return f'{self.item.name}: {sign}{self.quantity} ({self.get_movement_type_display()})'
