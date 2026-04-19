from django.db import models


class Service(models.Model):
    """Servicio ofrecido en la barbería.

    Categorías:
      individual  → Solo barba, cejas, etc.
      silver      → Corte + Shampoo + Bebida de cortesía
      gold        → Silver + acceso Club + servicios premium (masajes)
      diamond     → Gold + sorteos individuales y beneficios extra
      vip         → Servicios exclusivos de Frank: tratamientos 2h, keratinas, servicios para damas
    """
    CATEGORY_CHOICES = [
        ('individual', 'Servicio Individual'),
        ('silver', 'Membresía Silver'),
        ('gold', 'Membresía Gold'),
        ('diamond', 'Membresía Diamond'),
        ('vip', 'VIP / Exclusivo Frank'),
    ]

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='individual')
    price = models.DecimalField(max_digits=10, decimal_places=0)
    duration_minutes = models.IntegerField(default=60)
    features = models.JSONField(default=list, blank=True)
    includes_beverage = models.BooleanField(default=False,
        help_text='Si activa, descuenta automáticamente bebida del inventario al confirmar venta.')
    is_active = models.BooleanField(default=True)
    is_popular = models.BooleanField(default=False)
    display_order = models.IntegerField(default=0)
    # Restricción de barbero: si se asigna, solo ese barbero puede ofrecer este servicio
    exclusive_barber = models.ForeignKey(
        'barbers.Barber',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='exclusive_services',
        help_text='Dejar vacío para servicio disponible para todos los barberos.'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Servicio'
        verbose_name_plural = 'Servicios'
        ordering = ['display_order', 'name']

    def __str__(self):
        return f'{self.name} — ${self.price:,.0f}'

    @property
    def is_membership(self):
        return self.category in ('silver', 'gold', 'diamond')

    @property
    def tier_level(self):
        """Nivel numérico del tier para comparaciones (mayor = mejor)."""
        levels = {'individual': 0, 'silver': 1, 'gold': 2, 'diamond': 3, 'vip': 4}
        return levels.get(self.category, 0)

