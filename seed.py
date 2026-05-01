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

# Crear/Actualizar servicios oficiales
services_data = [
    {'name': 'Corte Imperial', 'slug': 'corte-imperial', 'price': 30000,
     'duration_minutes': 30, 'features': ['Asesoría visajista', 'Precisión milimétrica', 'Acabado impecable']},
    {'name': 'Corte + Freestyle', 'slug': 'corte-freestyle', 'price': 35000,
     'duration_minutes': 40, 'features': ['Corte completo', 'Diseño freestyle personalizado', 'Cejas y styling'],
     'is_popular': True},
    {'name': 'Corte con Barba', 'slug': 'corte-barba', 'price': 40000,
     'duration_minutes': 40, 'features': ['Corte de cabello', 'Diseño de barba', 'Cejas y styling']},
    {'name': 'The Club Experience', 'slug': 'club-experience', 'price': 60000,
     'duration_minutes': 60, 'features': ['Corte imperial', 'Diseño de barba ritual', 'Vapor ozono', 'Mascarilla'],
     'is_popular': True},
    {'name': 'Ritual de Barba', 'slug': 'ritual-barba', 'price': 25000,
     'duration_minutes': 30, 'features': ['Diseño a navaja', 'Toallas calientes aromáticas', 'Aceites premium']},
    {'name': 'Corte para Dama', 'slug': 'corte-dama', 'price': 35000,
     'duration_minutes': 40, 'features': ['Corte personalizado', 'Limpieza de cejas con cuchilla']},
    {'name': 'Freestyle Creativo', 'slug': 'freestyle-creativo', 'price': 40000,
     'duration_minutes': 45, 'features': ['Diseño artístico', 'Freestyle avanzado', 'Styling premium']},
    {'name': 'Rayitos o Mechas', 'slug': 'rayitos-mechas', 'price': 225000,
     'duration_minutes': 120, 'features': ['Color profesional', 'Proceso completo', 'Post-tratamiento']},
    {'name': 'Trenzados', 'slug': 'trenzados', 'price': 70000,
     'duration_minutes': 90, 'features': ['Trenzado completo', 'Styling profesional']},
]

for i, svc in enumerate(services_data):
    Service.objects.update_or_create(
        slug=svc['slug'],
        defaults={**svc, 'display_order': i}
    )

# Limpiar barberos de prueba si existen
Barber.objects.filter(display_name__in=['Barbero Prueba', 'Juan Pérez', 'Carlos Estilista']).delete()
User.objects.filter(username__in=['barberoprueba', 'juan', 'carlos']).delete()

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
users_to_create = [
    {'username': 'camilorf', 'password': 'area30*', 'email': 'camilo@area30.co'},
    {'username': 'juandavid.castro', 'password': 'Liam2711*', 'email': 'juandavid@area30.co'},
    {'username': 'soporte_tecnico', 'password': 'soporte_tecnico_pass', 'email': 'soporte@area30.co'}, # Assuming some pass or keeping existing
]

for user_data in users_to_create:
    try:
        uname = user_data['username']
        user, created = User.objects.get_or_create(username=uname, defaults={'email': user_data['email']})
        user.set_password(user_data['password'])
        user.is_staff = True
        user.is_superuser = True
        user.save()
        UserProfile.objects.get_or_create(user=user, defaults={'role': 'superadmin'})
        print(f"OK: Usuario {uname} {'creado' if created else 'actualizado'} correctamente.")
    except Exception as e:
        print(f"No se pudo procesar al usuario {uname}: {e}")

# Eliminar usuarios antiguos si existen para evitar duplicados/confusión
User.objects.filter(username__in=['camilo', 'juan david', 'juandavid', 'juan.david']).delete()

# --- Asegurar que solo existan Camilo y Juan David como socios ---
try:
    from apps.roi.models import Partner
    
    # 1. Obtener usuarios canónicos
    camilo_user = User.objects.filter(username='camilorf').first()
    jd_user = User.objects.filter(username='juandavid.castro').first()
    
    # 2. Eliminar socios duplicados o con alias (manteniendo solo los que tengan estos usuarios)
    valid_users = [u for u in [camilo_user, jd_user] if u]
    Partner.objects.exclude(user__in=valid_users).delete()
    
    # 3. Crear/Asegurar socio Camilo
    if camilo_user:
        Partner.objects.update_or_create(
            user=camilo_user,
            defaults={'display_name': 'Camilo', 'share_percentage': 50.00}
        )
        
    # 4. Crear/Asegurar socio Juan David
    if jd_user:
        Partner.objects.update_or_create(
            user=jd_user,
            defaults={'display_name': 'Juan David', 'share_percentage': 50.00}
        )
except Exception as e:
    print(f"Error gestionando los socios únicos: {e}")

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
