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

# Limpiar barbero de prueba si existe
Barber.objects.filter(display_name='Barbero Prueba').delete()
User.objects.filter(username='barberoprueba').delete()

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

from apps.cashflow.models import PaymentMethod

pm1, _ = PaymentMethod.objects.get_or_create(slug='efectivo', defaults={'name': 'Efectivo', 'is_active': True, 'requires_reference': False})
pm2, _ = PaymentMethod.objects.get_or_create(slug='transferencia', defaults={'name': 'Transferencia (Nequi/Bancolombia)', 'is_active': True, 'requires_reference': True})

# Crear superusuarios automáticamente para Railway
usernames_to_promote = ['camilo', 'juan david', 'juandavid', 'juan.david']
for uname in usernames_to_promote:
    try:
        user, created = User.objects.get_or_create(username=uname, defaults={'email': f'{uname.replace(" ", "")}@area30.com'})
        if created:
            user.set_password('area30')
        user.is_staff = True
        user.is_superuser = True
        user.save()
        UserProfile.objects.get_or_create(user=user, defaults={'role': 'superadmin'})
    except Exception as e:
        print(f"No se pudo promover al usuario {uname}: {e}")

# Crear a Frank (Administrador Operativo)
try:
    frank, created_f = User.objects.get_or_create(username='frank', defaults={'email': 'frank@area30.com'})
    if created_f:
        frank.set_password('area30')
    frank.is_staff = True
    frank.save()
    UserProfile.objects.get_or_create(user=frank, defaults={'role': 'operational_admin'})
except Exception as e:
    print("Error creando a Frank:", e)

print("Superusuarios actualizados correctamente.")
