"""La última cita del domingo pasa a las 6:30 p.m. (petición del dueño, 26-jul-2026).

La migración 0011 dejó `last_start` en las 7 p.m., pero una cita de una hora
iniciada a esa hora termina a las 8, una hora después del cierre. Se mueve el
último turno agendable a las 18:30; la ventana sigue siendo 14:00–19:00.

Los festivos usan esta misma ventana en tiempo de ejecución
(`Barber.day_window`), así que no hay nada que migrar para ellos.
"""

from django.db import migrations

SUNDAY_SCHEDULE = {'start': '14:00', 'end': '19:00', 'last_start': '18:30'}

PREVIOUS_SUNDAY = {'start': '14:00', 'end': '19:00', 'last_start': '19:00'}


def set_last_slot_1830(apps, schema_editor):
    Barber = apps.get_model('barbers', 'Barber')
    for barber in Barber.objects.all():
        schedule = barber.schedule or {}
        schedule['sunday'] = SUNDAY_SCHEDULE.copy()
        barber.schedule = schedule
        barber.save(update_fields=['schedule'])


def restore_last_slot_1900(apps, schema_editor):
    Barber = apps.get_model('barbers', 'Barber')
    for barber in Barber.objects.all():
        schedule = barber.schedule or {}
        schedule['sunday'] = PREVIOUS_SUNDAY.copy()
        barber.schedule = schedule
        barber.save(update_fields=['schedule'])


class Migration(migrations.Migration):

    dependencies = [
        ('barbers', '0011_sunday_afternoon_schedule'),
    ]

    operations = [
        migrations.RunPython(set_last_slot_1830, restore_last_slot_1900),
    ]
