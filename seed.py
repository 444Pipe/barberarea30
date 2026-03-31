import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()

from django.contrib.auth.models import User
from apps.users.models import Barbershop
from apps.services.models import Service
from apps.barbers.models import Barber

with open('data.json', encoding='utf-8') as f:
    data = json.load(f)

# Create a barbershop
shop, _ = Barbershop.objects.get_or_create(
    id=1,
    defaults={'name': 'Area 30', 'address': 'Restrepo'}
)

from django.utils.text import slugify

for s in data.get('services', []):
    Service.objects.get_or_create(
        id=s['id'],
        defaults={
            'name': s['name'],
            'slug': slugify(s['name']),
            'price': s['price'],
            'duration_minutes': s.get('duration', 30),
            'is_active': True
        }
    )

u1, _ = User.objects.get_or_create(username='juan', defaults={'email': 'juan@test.com'})
b1, _ = Barber.objects.get_or_create(
    id=1,
    defaults={
        'user': u1,
        'barbershop': shop,
        'display_name': 'Juan Pérez',
        'is_available': True,
        'color_tag': '#D4AF37'
    }
)
if not b1.specialties.exists():
    b1.specialties.add(Service.objects.first())

u2, _ = User.objects.get_or_create(username='carlos', defaults={'email': 'carlos@test.com'})
b2, _ = Barber.objects.get_or_create(
    id=2,
    defaults={
        'user': u2,
        'barbershop': shop,
        'display_name': 'Carlos Estilista',
        'is_available': True,
        'color_tag': '#1A1A1A'
    }
)
if not b2.specialties.exists():
    b2.specialties.add(Service.objects.last())

print("Datos cargados correctamente")
