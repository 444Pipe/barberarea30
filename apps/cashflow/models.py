from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
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
    added_value_amount = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    added_value_description = models.CharField(max_length=200, blank=True)
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
        ('shared', 'Mitad y Mitad (50% / 50%)'),
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

    # --- NUEVO: Estado de aprobación ---
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    APPROVAL_STATUS_CHOICES = [
        (STATUS_PENDING, 'Pendiente'),
        (STATUS_APPROVED, 'Aprobada'),
        (STATUS_REJECTED, 'Rechazada'),
    ]
    approval_status = models.CharField(max_length=10, choices=APPROVAL_STATUS_CHOICES, default=STATUS_PENDING)
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_sales'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rejected_sales'
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Venta / Checkout'
        verbose_name_plural = 'Ventas'
        ordering = ['-created_at']

    def __str__(self):
        desc = self.service.name if self.service else "Venta General"
        return f'Venta #{self.pk} — {desc} — ${self.final_price:,.0f}'

    def save(self, *args, **kwargs):
        self.final_price = self.base_price + self.added_value_amount - self.discount_amount
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
    
    # Banderas para aislar flujo de pago.
    # OJO (Frank): para él `is_paid` significa "procesada por un cierre diario",
    # NO "pagada en su totalidad" — el cierre puede pagar un monto distinto al
    # devengado y la diferencia se arrastra como saldo. Su deuda/saldo real se
    # deriva SIEMPRE con services.compute_frank_ledger(), nunca desde estos flags.
    is_paid = models.BooleanField(default=False, help_text='¿Ya fue pagada esta comisión al barbero?')
    paid_at = models.DateTimeField(null=True, blank=True)
    is_paid_in_daily_close = models.BooleanField(default=False, help_text='Usado para liquidaciones diarias automatizadas (ej. Frank)')
    # Liquidación manual (barberos no-Frank): pago concreto que saldó esta
    # comisión. Sin esto, `is_paid` no dice CUÁL pago la cubrió y un pago
    # eliminado no se podría revertir con precisión.
    paid_in_payment = models.ForeignKey(
        'BarberPayment', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='commissions',
        help_text='Pago en el que se liquidó esta comisión (barberos no-Frank)'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Comisión'
        verbose_name_plural = 'Comisiones'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.sale.discount_assumed_by == Sale.BARBER_ASSUMES:
            # Barbero asume: la comisión se calcula sobre el precio FINAL (ya descontado)
            self.basis_amount = self.sale.final_price
        elif self.sale.discount_assumed_by == 'shared':
            # Mitad y mitad: se resta el 50% del descuento al precio base
            half_discount = self.sale.discount_amount / Decimal('2.0')
            self.basis_amount = self.sale.base_price + self.sale.added_value_amount - half_discount
        else:
            # Empresa asume (o sin descuento): comisión sobre el precio BASE
            self.basis_amount = self.sale.base_price + self.sale.added_value_amount

        self.commission_amount = (self.basis_amount * self.percentage) / Decimal('100.00')
        self.tip_amount = self.sale.tip_amount
        self.total_earnings = self.commission_amount + self.tip_amount
        super().save(*args, **kwargs)


class BarberAdvance(models.Model):
    """Adelanto / vale de préstamo a un barbero contra sus ganancias acumuladas.

    Cuando un barbero pide prestado parte de lo que ha hecho en la quincena, se
    registra aquí como un "vale". El monto se descuenta del acumulado pendiente
    al momento de liquidar (marcar pagado). Mientras no haya saldo a favor que
    cubra los vales, estos quedan pendientes (`is_settled=False`) y la deuda se
    arrastra automáticamente a la siguiente liquidación.
    """
    barber = models.ForeignKey(
        'barbers.Barber', on_delete=models.CASCADE, related_name='advances'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=0)
    reason = models.CharField(
        max_length=255, blank=True, help_text='Motivo del préstamo / vale'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='barber_advances_given'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Liquidación: se marca cuando el vale ya fue descontado en un pago.
    is_settled = models.BooleanField(
        default=False, help_text='¿Ya fue descontado en una liquidación al barbero?'
    )
    settled_at = models.DateTimeField(null=True, blank=True)
    # Cierre diario en el que se liquidó (solo Frank). Permite revertir la
    # liquidación si el cierre se elimina.
    settled_in_daily_close = models.ForeignKey(
        'DailyClose', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='settled_advances',
        help_text='Cierre diario en el que se liquidó este vale (solo Frank)'
    )
    # Liquidación manual (barberos no-Frank). Permite revertir el vale con
    # precisión si un superadmin elimina ese pago.
    settled_in_payment = models.ForeignKey(
        'BarberPayment', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='settled_advances',
        help_text='Pago en el que se descontó este vale (barberos no-Frank)'
    )

    class Meta:
        verbose_name = 'Adelanto / Vale de Barbero'
        verbose_name_plural = 'Adelantos / Vales de Barberos'
        ordering = ['-created_at']

    def __str__(self):
        name = self.barber.display_name if self.barber else '?'
        return f'Vale ${self.amount:,.0f} — {name}'


class BarberPayment(models.Model):
    """Pago real de dinero a un barbero. Dos orígenes, distinguidos por `daily_close`:

    - Frank (`daily_close` presente): lo genera el cierre diario. CASCADE a
      propósito: al borrar el cierre el pago desaparece y el saldo derivado se
      restaura solo. NO se borra de forma individual — el camino es el cierre.
    - Resto de barberos (`daily_close` nulo): lo genera `pay_barber_view` al
      marcar pagado. Las comisiones y vales que cubrió apuntan aquí
      (`commissions` / `settled_advances`), de modo que un superadmin puede
      eliminarlo y revertir exactamente lo que ese pago liquidó.

    El saldo corriente de Frank se DERIVA, nunca se almacena:
        saldo = Σ Commission.total_earnings − Σ BarberAdvance.amount − Σ BarberPayment.amount
    (ver services.compute_frank_ledger).
    """
    barber = models.ForeignKey(
        'barbers.Barber', on_delete=models.CASCADE, related_name='payments'
    )
    daily_close = models.ForeignKey(
        'DailyClose', null=True, blank=True, on_delete=models.CASCADE,
        related_name='barber_payments'
    )
    expense = models.ForeignKey(
        'Expense', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='barber_payments'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    suggested_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0,
        help_text='Saldo sugerido por el sistema al momento del pago')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='barber_payments_made'
    )
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Pago a Barbero'
        verbose_name_plural = 'Pagos a Barberos'
        ordering = ['-created_at']

    def __str__(self):
        name = self.barber.display_name if self.barber else '?'
        return f'Pago ${self.amount:,.0f} — {name}'


class InventorySale(models.Model):
    """Venta directa de un producto de inventario (Ej. Bebidas)."""
    item = models.ForeignKey(
        'inventory.InventoryItem', on_delete=models.SET_NULL, null=True, related_name='direct_sales'
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=0)
    total_price = models.DecimalField(max_digits=10, decimal_places=0)
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.SET_NULL, null=True, blank=True
    )
    sold_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='inventory_sales_made'
    )
    included_in_daily_close = models.ForeignKey(
        'DailyClose', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='inventory_sales'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Venta de Inventario'
        verbose_name_plural = 'Ventas de Inventario'
        ordering = ['-created_at']

    def __str__(self):
        item_name = self.item.name if self.item else 'Producto Eliminado'
        return f'{self.quantity}x {item_name} — ${self.total_price:,.0f}'

    def save(self, *args, **kwargs):
        self.total_price = self.quantity * self.unit_price
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
    # Fecha local (America/Bogota), no la del servidor en UTC: un egreso
    # registrado de noche debe contar en el día/mes correcto para el ROI.
    date = models.DateField(default=timezone.localdate)
    registered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    notes = models.TextField(blank=True)
    # Permitir adjuntar una imagen (foto o galería)
    image = models.ImageField(upload_to='expenses/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    included_in_daily_close = models.ForeignKey(
        'DailyClose', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='expenses'
    )

    class Meta:
        verbose_name = 'Egreso'
        verbose_name_plural = 'Egresos'
        ordering = ['-date', '-created_at']


class CashflowAlertLog(models.Model):
    """Dedup de alertas programadas: una fila por (tipo, día).

    El `create()` contra el UniqueConstraint es el candado entre múltiples
    workers de gunicorn (cada proceso corre su propio scheduler): el primero
    inserta y envía, los demás reciben IntegrityError y no re-envían.
    """
    alert_type = models.CharField(max_length=30)  # ej. 'close_reminder'
    date = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Alerta de Caja Enviada'
        verbose_name_plural = 'Alertas de Caja Enviadas'
        constraints = [
            models.UniqueConstraint(fields=['alert_type', 'date'], name='uniq_cashflow_alert_per_day'),
        ]

    def __str__(self):
        return f'{self.alert_type} — {self.date}'


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
        help_text='Ingresos brutos por ventas de servicios (sin propinas)')
    total_inventory_sales = models.DecimalField(max_digits=12, decimal_places=0, default=0,
        help_text='Ingresos por ventas directas de inventario (bebidas, etc.)')
    total_tips = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    total_commissions = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    total_expenses = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    net_income = models.DecimalField(max_digits=12, decimal_places=0, default=0,
        help_text='(Ventas Servicios + Ventas Inventario - Comisiones - Egresos Variables)')
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
