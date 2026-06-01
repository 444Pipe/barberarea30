"""Crea (o actualiza) el servicio Color a consulta.

Idempotente — usa update_or_create por slug. No depende de que se ejecute
seed_services para que el servicio aparezca en producción/local: con un
`manage.py migrate` queda dado de alta y visible en /api/servicios-nativos/.
"""
from django.db import migrations


COLOR_DEFAULTS = {
    'name': 'Color',
    'category': 'vip',
    'price': 0,
    'duration_minutes': 120,
    'description': 'Color para hombres y mujeres. Precio y tiempo según largo y producto. A consulta — escríbenos por WhatsApp.',
    'features': ['Diagnóstico capilar', 'Color profesional', 'Producto premium'],
    'requires_consultation': True,
    'is_active': True,
    # Posición 4: aparece después de Silver Dama y antes de Silver+Barba.
    # Eso lo deja en la 2ª-3ª fila del grid del wizard — visible sin mucho scroll.
    'display_order': 4,
}


def create_color(apps, schema_editor):
    Service = apps.get_model('services', 'Service')
    Service.objects.update_or_create(slug='color-cabello', defaults=COLOR_DEFAULTS)


def remove_color(apps, schema_editor):
    Service = apps.get_model('services', 'Service')
    Service.objects.filter(slug='color-cabello').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('services', '0005_service_requires_consultation'),
    ]

    operations = [
        migrations.RunPython(create_color, remove_color),
    ]
