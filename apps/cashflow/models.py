from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal


class PaymentMethod(models.Model):
    """Métodos de pago. Ej: Transferencia (Nequi, Bancolombia), Efectivo, Tarjeta."""
    name = models.CharField(max_length=50)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)
    requires_reference = models.BooleanField(default=False,
        help_text='Si requiere número de comprobante (ej: Transferencia)')

    class Meta:
        verbose_name = 'Método de Pago'
        verbose_name_plural = 'Métodos de Pago'
        ordering = ['name']

    def __str__(self):
        return self.name


class Sale(models.Model):
    """Registro final de la venta confirmada (Cierre del Checkout).

    Solo 'operational_admin' y superiores pueden crear ventas.
    Al confirmar, se asume que el servicio se pagó y se pueden registrar
    propinas, descuentos, y restar inventario.
    """
    booking = models.OneToOneField(
        'bookings.Booking', on_delete=models.CASCADE,
        related_name='sale', null=True, blank=True
    )
    barber = models.ForeignKey(
        'barbers.Barber', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sales'
    )
    service = models.ForeignKey(
        'services.Service', on_delete=models.SET_NULL, null=True, blank=True
    )
    # Totales
    base_price = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    final_price = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    tip_amount = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    total_paid = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    # Descuento: ¿quién asume? (Empresa o Barbero)
    COMPANY_ASSUMES = 'company'
    BARBER_ASSUMES = 'barber'
    DISCOUNT_ASSUMED_BY = [
        (COMPANY_ASSUMES, 'Empresa'),
        (BARBER_ASSUMES, 'Barbero'),
        ('none', 'No aplica'),
    ]
    discount_assumed_by = models.CharField(max_length=20, choices=DISCOUNT_ASSUMED_BY, default='none')
    # Pago
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.SET_NULL, null=True, blank=True
    )
    payment_reference = models.CharField(max_length=100, blank=True)
    # Auditoría
    confirmed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='confirmed_sales'
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Si esta venta ya fue contabilizada en un cierre diario
    included_in_daily_close = models.ForeignKey(
        'DailyClose', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='sales'
    )

    class Meta:
        verbose_name = 'Venta / Checkout'
        verbose_name_plural = 'Ventas'
        ordering = ['-created_at']

    def __str__(self):
        desc = self.service.name if self.service else "Venta General"
        return f'Venta #{self.pk} — {desc} — ${self.final_price:,.0f}'

    def save(self, *args, **kwargs):
        self.final_price = self.base_price - self.discount_amount
        self.total_paid = self.final_price + self.tip_amount
        super().save(*args, **kwargs)


class Commission(models.Model):
    """Comisiones de los barberos.

    Se genera automáticamente cada vez que se crea una Sale.
    Frank / Barberos ganan un % configurado en su perfil (o default 50%).
    """
    sale = models.OneToOneField(
        Sale, on_delete=models.CASCADE, related_name='commission'
    )
    barber = models.ForeignKey(
        'barbers.Barber', on_delete=models.CASCADE, related_name='commissions'
    )
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=50.00)
    # Base real sobre la que se calcula (ej. si el barbero asume descuento)
    basis_amount = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    tip_amount = models.DecimalField(max_digits=10, decimal_places=0, default=0,
        help_text='100% de propinas va para el barbero')
    total_earnings = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Comisión'
        verbose_name_plural = 'Comisiones'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        # Lógica de cálculo:
        if self.sale.discount_assumed_by == Sale.BARBER_ASSUMES:
            # Barbero asume: la comisión se calcula sobre el precio FINAL (ya descontado)
            self.basis_amount = self.sale.final_price
        else:
            # Empresa asume (o sin descuento): comisión sobre el precio BASE
            self.basis_amount = self.sale.base_price

        self.commission_amount = (self.basis_amount * self.percentage) / Decimal('100.00')
        self.tip_amount = self.sale.tip_amount
        self.total_earnings = self.commission_amount + self.tip_amount
        super().save(*args, **kwargs)


class Expense(models.Model):
    """Egresos fijos y variables."""
    # Solo superadmins gestionan los "fixed". Operativos gestionan "variable".
    EXPENSE_TYPES = [
        ('fixed', 'Fijo (Arriendo, Servicios, Nómina)'),
        ('variable', 'Variable (Mantenimiento, Compras menores)'),
        ('inventory', 'Compra de Inventario'),
    ]

    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    expense_type = models.CharField(max_length=20, choices=EXPENSE_TYPES, default='variable')
    date = models.DateField(auto_now_add=True)
    registered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    included_in_daily_close = models.ForeignKey(
        'DailyClose', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='expenses'
    )

    class Meta:
        verbose_name = 'Egreso'
        verbose_name_plural = 'Egresos'
        ordering = ['-date', '-created_at']


class DailyClose(models.Model):
    """Cierre de Caja Diario.

    Frank (operativo) o superadmin genera esto. Agrupa ventas y egresos del día.
    Es inmutable una vez cerrado. Un solo cierre por día.
    """
    date = models.DateField(unique=True)
    closed_at = models.DateTimeField(auto_now_add=True)
    closed_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='daily_closes'
    )
    total_sales = models.DecimalField(max_digits=12, decimal_places=0, default=0,
        help_text='Ingresos brutos por ventas (sin propinas)')
    total_tips = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    total_commissions = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    total_expenses = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    net_income = models.DecimalField(max_digits=12, decimal_places=0, default=0,
        help_text='(Ventas - Comisiones - Egresos Variables)')
    notes = models.TextField(blank=True)
    is_verified = models.BooleanField(default=False,
        help_text='SuperAdmin verifica que el cuadre sea correcto y consignado')
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verified_daily_closes'
    )

    class Meta:
        verbose_name = 'Cierre Diario'
        verbose_name_plural = 'Cierres Diarios'
        ordering = ['-date']

    def __str__(self):
        return f'Cierre {self.date} — Neto: ${self.net_income:,.0f}'
