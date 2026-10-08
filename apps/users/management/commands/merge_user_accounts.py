"""Une dos cuentas de la misma persona en una sola y borra la que sobra.

Caso real (oct-2026): Cristian tenía `cristiang` (barbero, con 317 comisiones,
383 bloqueos y 300 ventas confirmadas) y `cristian.admin` (socio/superadmin,
dueño del puesto de socio en el ROI). Borrar `cristiang` a secas habría
arrastrado en CASCADA su perfil de barbero y todas sus comisiones. Este comando
mueve TODO lo que apunta a la cuenta que se va hacia la que se queda, y solo
entonces la borra, ya vacía.

    # Ver qué haría (no cambia nada):
    python manage.py merge_user_accounts --keep cristian.admin --remove cristiang
    # Aplicar:
    python manage.py merge_user_accounts --keep cristian.admin --remove cristiang \\
        --email cristiangome930@gmail.com --apply

Reglas:
  - FK a User → se reasignan a la cuenta que se queda (ventas, auditoría…).
  - OneToOne (perfil de barbero, puesto de socio…) → se mueve si la que se
    queda no tiene uno; si las dos tienen, se aborta (salvo UserProfile: se
    conserva el de la que se queda).
  - Todo en una transacción: o se hace completo o no se hace nada.
  - Queda un AuditLog nuevo con la unión y cuántas filas se movieron (los
    registros de auditoría de la cuenta borrada pasan a la que se queda; sin
    eso quedarían sin autor por el SET_NULL).
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.users.models import UserProfile

# Tablas que no tiene sentido reasignar: se van con la cuenta borrada.
SKIP_APPS = {'token_blacklist', 'sessions'}


class Command(BaseCommand):
    help = 'Une dos cuentas de usuario (mueve todo a --keep y borra --remove).'

    def add_arguments(self, parser):
        parser.add_argument('--keep', required=True, help='Usuario que se queda')
        parser.add_argument('--remove', required=True, help='Usuario que se borra')
        parser.add_argument('--email', default='', help='Email final de la cuenta que se queda')
        parser.add_argument('--role', default='', help='Rol final (ej. superadmin). Por defecto, el de --keep')
        parser.add_argument('--apply', action='store_true', help='Aplicar (sin esto solo muestra)')

    def handle(self, *args, **opts):
        try:
            keep = User.objects.get(username=opts['keep'])
            remove = User.objects.get(username=opts['remove'])
        except User.DoesNotExist as exc:
            raise CommandError(f'Usuario no encontrado: {exc}')
        if keep.pk == remove.pk:
            raise CommandError('--keep y --remove son la misma cuenta.')

        apply = opts['apply']
        self.stdout.write(f'{"APLICANDO" if apply else "SIMULACIÓN (usa --apply)"}: '
                          f'{remove.username} (#{remove.pk}) -> {keep.username} (#{keep.pk})')

        moved = {}
        with transaction.atomic():
            for rel in User._meta.related_objects:
                model = rel.related_model
                if rel.many_to_many or model._meta.app_label in SKIP_APPS:
                    continue
                field = rel.field.name
                qs = model._default_manager.filter(**{field: remove})
                n = qs.count()
                if not n:
                    continue
                label = f'{model._meta.label}.{field}'
                if rel.one_to_one:
                    if model is UserProfile:
                        self.stdout.write(f'  {label}: se borra con la cuenta (se conserva el de {keep.username})')
                        continue
                    if model._default_manager.filter(**{field: keep}).exists():
                        raise CommandError(f'{label}: las dos cuentas tienen uno; no se puede unir.')
                    self.stdout.write(f'  {label}: se MUEVE a {keep.username}')
                else:
                    self.stdout.write(f'  {label}: {n} fila(s) se reasignan a {keep.username}')
                moved[label] = n
                if apply:
                    qs.update(**{field: keep})

            for group in remove.groups.all():
                if apply:
                    keep.groups.add(group)

            role = opts['role']
            email = opts['email']
            profile = getattr(keep, 'profile', None)
            if role:
                self.stdout.write(f'  rol final de {keep.username}: {role}')
            if email:
                self.stdout.write(f'  email final de {keep.username}: {email}')
            self.stdout.write(f'  se BORRA la cuenta {remove.username} (#{remove.pk})')

            if apply:
                if role and profile is not None and profile.role != role:
                    profile.role = role
                    profile.save(update_fields=['role'])
                if role == 'superadmin':
                    keep.is_staff = True
                    keep.is_superuser = True
                if email:
                    keep.email = email
                keep.save()
                from apps.analytics.models import AuditLog
                AuditLog.objects.create(
                    user=keep, action='update', model_name='User', object_id=remove.pk,
                    object_repr=f'Unión de cuentas: {remove.username} -> {keep.username}',
                    extra_data={
                        'msg': (f'La cuenta {remove.username} (#{remove.pk}) se unió a '
                                f'{keep.username} y se borró; sus filas se reasignaron.'),
                        'reassigned': moved,
                    },
                )
                remove.delete()
                self.stdout.write(self.style.SUCCESS('Listo: cuentas unidas.'))
            else:
                self.stdout.write(self.style.WARNING('Simulación: no se cambió nada.'))
