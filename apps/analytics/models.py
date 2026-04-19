from django.db import models
from django.contrib.auth.models import User


class AuditLog(models.Model):
    """Registro de auditoría inmutable.

    Cada vez que un usuario modifica un dato sensible (precios, personal,
    egresos fijos, promociones) se crea un registro aquí.
    Este modelo NO permite actualizaciones ni eliminaciones por diseño.
    Solo los SuperAdministradores pueden consultarlo.
    """
    ACTION_CHOICES = [
        ('create', 'Creación'),
        ('update', 'Modificación'),
        ('delete', 'Eliminación'),
        ('login', 'Inicio de sesión'),
        ('logout', 'Cierre de sesión'),
        ('price_change', 'Cambio de precio'),
        ('promotion', 'Promoción / Descuento'),
        ('daily_close', 'Cierre de caja'),
        ('payment', 'Registro de pago'),
        ('refund', 'Reembolso'),
        ('inventory', 'Movimiento de inventario'),
        ('commission', 'Comisión registrada'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=100, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_repr = models.CharField(max_length=300, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    extra_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Registro de Auditoría'
        verbose_name_plural = 'Registros de Auditoría'
        ordering = ['-created_at']
        # El registro de auditoría es inmutable: solo se permite agregar y ver
        default_permissions = ('add', 'view')

    def __str__(self):
        user_str = self.user.username if self.user else 'Sistema'
        return f'[{self.created_at:%Y-%m-%d %H:%M}] {user_str} — {self.get_action_display()} — {self.object_repr}'

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError('Los registros de auditoría son inmutables y no pueden modificarse.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Los registros de auditoría son inmutables y no pueden eliminarse.')


def log_audit(user, action, obj=None, changes=None, request=None, extra_data=None):
    """Helper para crear entradas de auditoría de forma sencilla.

    Uso:
        log_audit(request.user, 'price_change', service, {'price': [old, new]}, request)
    """
    ip = None
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        ip = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.META.get('REMOTE_ADDR')

    AuditLog.objects.create(
        user=user,
        action=action,
        model_name=obj.__class__.__name__ if obj else '',
        object_id=getattr(obj, 'pk', None),
        object_repr=str(obj) if obj else '',
        changes=changes or {},
        ip_address=ip,
        extra_data=extra_data or {},
    )
