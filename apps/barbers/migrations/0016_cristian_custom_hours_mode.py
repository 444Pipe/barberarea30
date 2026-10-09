"""Cristian pasa a "horario a elección" (oct-2026).

Hasta ahora vivía con un bloqueo de día completo, todos los días, hasta
jun-2027 (265 filas), y lo levantaba a mano cuando quería trabajar. Con el
modo `only_custom_hours` no recibe reservas salvo en las franjas que él abra
(BarberWorkHours), así que esos bloqueos de día completo ya sobran: se borran
solo los FUTUROS sin motivo (de hoy en adelante, 00:00–23:59). El historial
pasado se queda.

Va en una migración y no a mano para que el orden sea seguro: primero existe
el modo y en el mismo despliegue se quitan los bloqueos. Al revés, Cristian
quedaría abierto todo el día en la web.
"""
from datetime import time

from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    Barber = apps.get_model('barbers', 'Barber')
    BarberUnavailability = apps.get_model('barbers', 'BarberUnavailability')
    cristian = Barber.objects.filter(user__username='cristian.admin').first()
    if cristian is None:
        return
    cristian.only_custom_hours = True
    cristian.save(update_fields=['only_custom_hours'])
    BarberUnavailability.objects.filter(
        barber=cristian,
        date__gte=timezone.localdate(),
        start_time=time(0, 0),
        end_time__gte=time(23, 59),
        reason='',
    ).delete()


def backwards(apps, schema_editor):
    # No se recrean los bloqueos: apagar el modo devuelve el horario semanal.
    Barber = apps.get_model('barbers', 'Barber')
    Barber.objects.filter(user__username='cristian.admin').update(only_custom_hours=False)


class Migration(migrations.Migration):

    dependencies = [
        ('barbers', '0015_barber_only_custom_hours'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
