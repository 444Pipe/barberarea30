from django.db import migrations

def link_dama_to_frank(apps, schema_editor):
    Service = apps.get_model('services', 'Service')
    Barber = apps.get_model('barbers', 'Barber')
    User = apps.get_model('auth', 'User')
    Barbershop = apps.get_model('users', 'Barbershop')

    # Find Frank
    frank_barber = Barber.objects.filter(display_name__icontains='frank').first()
    
    if not frank_barber:
        # Try finding user
        user = User.objects.filter(username__icontains='frank').first() or \
               User.objects.filter(email='frankodraw@gmail.com').first() or \
               User.objects.filter(username__icontains='franko').first()
        
        if user:
            barbershop = Barbershop.objects.first()
            if not barbershop:
                barbershop = Barbershop.objects.create(name='Área 30 Barber Club')
            
            frank_barber, created = Barber.objects.get_or_create(
                user=user,
                defaults={
                    'barbershop': barbershop,
                    'display_name': 'Franko',
                    'is_available': True,
                    'color_tag': '#D4AF37'
                }
            )
    
    if frank_barber:
        # Link all Dama services
        dama_services = Service.objects.filter(name__icontains='dama') | Service.objects.filter(slug__icontains='dama')
        for srv in dama_services:
            srv.exclusive_barber = frank_barber
            srv.save()
            print(f"Service {srv.name} linked to {frank_barber.display_name}")
    else:
        print("Frank not found in migration!")

class Migration(migrations.Migration):

    dependencies = [
        ('services', '0003_add_dama_services'),
        ('barbers', '0007_frank_fix_schedule'),
    ]

    operations = [
        migrations.RunPython(link_dama_to_frank),
    ]
