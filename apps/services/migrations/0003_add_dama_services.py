from django.db import migrations

def add_dama_services(apps, schema_editor):
    Service = apps.get_model('services', 'Service')
    Barber = apps.get_model('barbers', 'Barber')
    
    frank = Barber.objects.filter(user__username='frank').first()
    if not frank:
        print("Frank no encontrado, no se pueden asignar servicios exclusivos.")
        return

    services = [
        {
            'name': 'Servicio Silver Dama',
            'slug': 'silver-dama',
            'description': 'Corte sencillo, despunte recto, en forma de "U" o "V".',
            'category': 'vip',
            'price': 35000,
            'duration_minutes': 60,
            'includes_beverage': True,
            'exclusive_barber': frank,
            'display_order': 20
        },
        {
            'name': 'Servicio Gold Dama',
            'slug': 'gold-dama',
            'description': 'Corte sencillo, despunte recto, en forma de "U" o "V", shampoo, tratamiento y masaje capilar.',
            'category': 'vip',
            'price': 50000,
            'duration_minutes': 90,
            'includes_beverage': True,
            'exclusive_barber': frank,
            'display_order': 21
        },
        {
            'name': 'Servicio Diamond VIP Dama',
            'slug': 'diamond-vip-dama',
            'description': 'Corte estructurado/avanzado, shampoo, tratamiento, masaje capilar, masaje cervical, cepillado/planchado.',
            'category': 'vip',
            'price': 70000,
            'duration_minutes': 120,
            'includes_beverage': True,
            'exclusive_barber': frank,
            'display_order': 22
        }
    ]

    for s_data in services:
        slug = s_data.pop('slug')
        Service.objects.update_or_create(slug=slug, defaults=s_data)

def remove_dama_services(apps, schema_editor):
    Service = apps.get_model('services', 'Service')
    Service.objects.filter(slug__in=['silver-dama', 'gold-dama', 'diamond-vip-dama']).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('services', '0002_service_category_service_exclusive_barber_and_more'),
        ('barbers', '0007_frank_fix_schedule'),
    ]

    operations = [
        migrations.RunPython(add_dama_services, remove_dama_services),
    ]
