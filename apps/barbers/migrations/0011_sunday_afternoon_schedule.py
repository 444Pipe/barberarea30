"""Domingos de 2 a 7 p.m. (petición de los socios, 26-jul-2026).

Antes el domingo estaba en 10:00–15:00, por eso la web seguía ofreciendo horas
de la mañana. Se pasa a 14:00–19:00 con `last_start` en las 7 p.m. (esa es la
hora de la ÚLTIMA cita, no la hora en que el servicio debe estar terminado).

Los festivos toman esta misma ventana en tiempo de ejecución
(`Barber.day_window`), así que no hay nada que migrar para ellos.
"""

from django.db import migrations

SUNDAY_SCHEDULE = {'start': '14:00', 'end': '19:00', 'last_start': '19:00'}

PREVIOUS_SUNDAY = {'start': '10:00', 'end': '15:00'}


def set_sunday_afternoon(apps, schema_editor):
    Barber = apps.get_model('barbers', 'Barber')
    for barber in Barber.objects.all():
        schedule = barber.schedule or {}
        schedule['sunday'] = SUNDAY_SCHEDULE.copy()
        barber.schedule = schedule
        barber.save(update_fields=['schedule'])


def restore_sunday_morning(apps, schema_editor):
    Barber = apps.get_model('barbers', 'Barber')
    for barber in Barber.objects.all():
        schedule = barber.schedule or {}
        schedule['sunday'] = PREVIOUS_SUNDAY.copy()
        barber.schedule = schedule
        barber.save(update_fields=['schedule'])


class Migration(migrations.Migration):

    dependencies = [
        ('barbers', '0010_barber_commission_percentage'),
    ]

    operations = [
        migrations.RunPython(set_sunday_afternoon, restore_sunday_morning),
    ]
