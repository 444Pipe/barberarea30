"""
ROI & Ganancias — Modelos de Datos.

Maneja:
  - PartnerInvestment  : Inversión inicial de cada socio (DecimalField).
  - MonthlyROISnapshot : Snapshot mensual consolidado (calculado el 1ro de cada mes).
"""
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


# ─────────────────────────────────────────────────────────
# Socios / Partners
# ─────────────────────────────────────────────────────────

class Partner(models.Model):
    """Socio de la barbería. Vinculado a un usuario Django."""
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='partner_profile',
    )
    display_name = models.CharField(max_length=100, verbose_name='Nombre del Socio')
    share_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('50.00'),
        verbose_name='% de participación',
        help_text='Porcentaje de las ganancias netas que le corresponde a este socio.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Socio'
        verbose_name_plural = 'Socios'
        ordering = ['display_name']

    def __str__(self):
        return self.display_name


# ─────────────────────────────────────────────────────────
# Inversión Inicial
# ─────────────────────────────────────────────────────────

class PartnerInvestment(models.Model):
    """
    Registro de la inversión inicial de un socio.
    Se pueden tener múltiples registros por socio (ej. aportes escalonados),
    pero lo más común es uno por socio.
    Siempre usar DecimalField para evitar errores de punto flotante con cifras grandes.
    """
    partner = models.ForeignKey(
        Partner,
        on_delete=models.CASCADE,
        related_name='investments',
        verbose_name='Socio',
    )
    amount = models.DecimalField(
        max_digits=15, decimal_places=0,
        verbose_name='Monto Invertido (COP)',
    )
    description = models.CharField(
        max_length=255, blank=True,
        verbose_name='Descripción',
        help_text='Ej: Aporte inicial, Compra de equipos, Adecuaciones locativas…',
    )
    date = models.DateField(default=timezone.now, verbose_name='Fecha del Aporte')
    registered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name='Registrado por',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Inversión del Socio'
        verbose_name_plural = 'Inversiones de Socios'
        ordering = ['-date']

    def __str__(self):
        return f'{self.partner.display_name} — ${self.amount:,.0f} COP ({self.date})'


# ─────────────────────────────────────────────────────────
# Snapshot Mensual de ROI
# ─────────────────────────────────────────────────────────

class MonthlyROISnapshot(models.Model):
    """
    Consolidado mensual que captura las ganancias netas del mes cerrado y
    cómo se distribuyen entre los socios para amortizar su inversión inicial.

    Creado automáticamente mediante APScheduler el 1ro de cada mes,
    o manualmente desde el panel de administración.

    Campo 'is_locked': una vez verificado y cerrado, no se puede editar.
    """
    year = models.PositiveSmallIntegerField(verbose_name='Año')
    month = models.PositiveSmallIntegerField(verbose_name='Mes (1-12)')

    # ── Financiero Global ──
    gross_income = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Ingresos Brutos (Servicios + Inventario)',
        help_text='gross_services + total_inventory_sales',
    )
    # Desglose de Bruto
    gross_services = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Ingresos por Servicios',
        help_text='Suma de Sale.final_price de ventas aprobadas del mes.',
    )
    total_inventory_sales = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Ingresos por Venta de Inventario',
        help_text='Suma de InventorySale.total_price del mes.',
    )
    total_commissions = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Total Comisiones Barberos',
        help_text='40% staff general / 50% Frank. Suma de Commission.commission_amount del mes.',
    )
    # Desglose de Egresos
    total_expenses = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Total Egresos (Fijos + Operativos)',
    )
    total_fixed_expenses = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Egresos Fijos (Arriendo, Servicios, Nómina)',
        help_text='Expense.amount donde expense_type=fixed.',
    )
    total_operational_expenses = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Egresos Operativos (Variables + Inventario)',
        help_text='Expense.amount donde expense_type IN (variable, inventory), excluyendo "Pago Diario: Franko" (ya está en comisiones).',
    )
    net_income = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Ganancia Neta del Mes',
        help_text='gross_income - total_commissions - total_fixed_expenses - total_operational_expenses',
    )

    # ── Control ──
    is_locked = models.BooleanField(
        default=False,
        verbose_name='¿Cerrado/Bloqueado?',
        help_text='Una vez bloqueado no puede modificarse.',
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name='Generado por',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, verbose_name='Notas')

    class Meta:
        verbose_name = 'Snapshot Mensual ROI'
        verbose_name_plural = 'Snapshots Mensuales ROI'
        ordering = ['-year', '-month']
        unique_together = [('year', 'month')]

    def __str__(self):
        import calendar
        month_name = calendar.month_name[self.month]
        return f'ROI {month_name} {self.year} — Neto: ${self.net_income:,.0f} COP'

    def compute_net(self):
        """Recalcula ganancia neta en memoria (no guarda)."""
        return (
            self.gross_income
            - self.total_commissions
            - self.total_fixed_expenses
            - self.total_operational_expenses
        )


class PartnerMonthlyShare(models.Model):
    """
    Distribución de la ganancia neta mensual para UN socio específico.
    Vinculado a un MonthlyROISnapshot.
    """
    snapshot = models.ForeignKey(
        MonthlyROISnapshot,
        on_delete=models.CASCADE,
        related_name='partner_shares',
    )
    partner = models.ForeignKey(
        Partner,
        on_delete=models.CASCADE,
        related_name='monthly_shares',
    )
    share_percentage = models.DecimalField(
        max_digits=5, decimal_places=2,
        verbose_name='% Aplicado',
    )
    gross_share = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Monto Bruto a Recibir',
        help_text='net_income * share_percentage / 100',
    )
    # Saldo de inversión ANTES de este mes
    investment_balance_before = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Saldo de Inversión Pendiente (Inicio del Mes)',
    )
    # Cuánto de la ganancia se aplica a amortizar inversión
    amortization_applied = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Amortización Aplicada',
        help_text='min(gross_share, investment_balance_before)',
    )
    # Saldo de inversión DESPUÉS de este mes
    investment_balance_after = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Saldo de Inversión Pendiente (Fin del Mes)',
    )
    # Excedente que va al bolsillo del socio (si la inversión ya está recuperada)
    cash_out = models.DecimalField(
        max_digits=15, decimal_places=0, default=0,
        verbose_name='Disponible para el Socio (Efectivo)',
        help_text='gross_share - amortization_applied',
    )

    class Meta:
        verbose_name = 'Participación Mensual de Socio'
        verbose_name_plural = 'Participaciones Mensuales de Socios'
        unique_together = [('snapshot', 'partner')]

    def __str__(self):
        return f'{self.partner.display_name} — {self.snapshot}'
