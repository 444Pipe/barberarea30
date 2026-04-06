import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()

from django.contrib.auth.models import User
from apps.users.models import Barbershop, UserProfile
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
u1.set_password('area30')
u1.save()
UserProfile.objects.get_or_create(user=u1, defaults={'role': 'barber', 'barbershop': shop})
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
u2.set_password('area30')
u2.save()
UserProfile.objects.get_or_create(user=u2, defaults={'role': 'barber', 'barbershop': shop})
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

# Barbero Exclusivo de Prueba para Demostraciones
u_prueba, _ = User.objects.get_or_create(username='barberoprueba', defaults={'email': 'prueba@test.com'})
u_prueba.set_password('area30')
u_prueba.save()
UserProfile.objects.get_or_create(user=u_prueba, defaults={'role': 'barber', 'barbershop': shop})

b_prueba, _ = Barber.objects.get_or_create(
    id=3,
    defaults={
        'user': u_prueba,
        'barbershop': shop,
        'display_name': 'Barbero Prueba',
        'is_available': True,
        'color_tag': '#22C55E'  # Verde distintivo
    }
)
if not b_prueba.specialties.exists() and Service.objects.exists():
    # Asignarle todos los servicios existentes para flexibilidad en las pruebas
    b_prueba.specialties.set(Service.objects.all())

print("Datos cargados correctamente")
# Asegurarnos de que la tabla bookings_blockeddate exista en producción si la migración falló misteriosamente
from django.db import connection
from apps.bookings.models import BlockedDate

try:
    # Verificamos si la tabla de verdad falta
    BlockedDate.objects.exists()
except Exception as check_err:
    try:
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(BlockedDate)
        print("✓ Tabla de BlockedDate creada limpiamente vía Schema Editor")
    except Exception as e:
        print("⚠ Fallo forzando la tabla (probablemente ya existe o hay otro error):", e)

