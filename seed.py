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

# Ya no se crean servicios desde data.json, solo se usarán los ingresados por el usuario.

# Limpiar barberos de prueba si existen
Barber.objects.filter(display_name__in=['Barbero Prueba', 'Juan Pérez', 'Carlos Estilista']).delete()
User.objects.filter(username__in=['barberoprueba', 'juan', 'carlos']).delete()

# Limpiar servicios ficticios
Service.objects.filter(name__in=['Corte Básico', 'Corte + Freestyle', 'Corte con Barba', 'Corte para Dama']).delete()

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

# --- NUEVO: Autocuración para cashflow_sale.approval_status ---
from apps.cashflow.models import Sale
try:
    # Intentamos una consulta que use la columna
    Sale.objects.filter(approval_status='approved').exists()
except Exception:
    print("⚠ Columna 'approval_status' no encontrada en cashflow_sale. Intentando crearla...")
    try:
        with connection.schema_editor() as schema_editor:
            from django.db import models
            # Añadir el campo manualmente vía SchemaEditor
            field = models.CharField(max_length=10, choices=[('pending', 'Pendiente'), ('approved', 'Aprobada'), ('rejected', 'Rechazada')], default='pending')
            field.set_attributes_from_name('approval_status')
            schema_editor.add_field(Sale, field)
        print("✓ Columna 'approval_status' creada exitosamente.")
    except Exception as e:
        print("⚠ No se pudo crear la columna manualmente:", e)

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
