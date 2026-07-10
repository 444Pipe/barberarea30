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

# Crear/Actualizar servicios oficiales.
# IMPORTANTE: este listado tiene que estar sincronizado con
# apps/services/management/commands/seed_services.py — son la fuente de la
# verdad para los servicios activos. Si agregás uno acá, agregalo también allá.
services_data = [
    {'name': 'Diseño de cejas', 'slug': 'diseno-de-cejas', 'price': 5000,
     'duration_minutes': 15,
     'description': 'Asesoría de forma según rostro, A navaja, Perfilado milimétrico',
     'features': [
         'Asesoría de forma según rostro',
         'A navaja',
         'Perfilado milimétrico',
     ]},
    {'name': 'Diseño de barba', 'slug': 'diseno-de-barba', 'price': 15000,
     'duration_minutes': 20,
     'description': 'Asesoría de forma, Toalla caliente preparatoria, Perfilado con navaja, Diseño milimétrico, Aceite o bálsamo hidratante',
     'features': [
         'Asesoría de forma',
         'Toalla caliente preparatoria',
         'Perfilado con navaja',
         'Diseño milimétrico',
         'Aceite o bálsamo hidratante',
     ]},
    {'name': 'Silver Premium', 'slug': 'silver-premium', 'price': 30000,
     'duration_minutes': 60, 'features': ['Corte', 'Lavado con shampoo específico', 'Masaje capilar', 'Estilismo', 'Bebidas ilimitadas']},
    {'name': 'Servicio Silver Dama', 'slug': 'servicio-silver-dama', 'price': 35000,
     'duration_minutes': 60,
     # description es lo que el wizard splittea para los bullets (por coma o " y ").
     # features se queda como referencia interna; el endpoint público usa description.
     'description': 'Corte sencillo, Despunte recto en U o V, Lavado con shampoo específico, Masaje capilar, Estilismo, Bebidas ilimitadas',
     'features': [
         'Corte sencillo (despunte recto, en forma de U o V)',
         'Lavado con shampoo específico',
         'Masaje capilar',
         'Estilismo y peinado final',
         'Bebidas ilimitadas',
     ]},
    # ─── Color a consulta — hombres y mujeres ──────────────────────
    # No es reservable online; el wizard abre WhatsApp. Es CRÍTICO que
    # aparezca aquí también o seed.py lo desactiva en cada boot.
    {'name': 'Color', 'slug': 'color-cabello',
     'category': 'vip', 'price': 0, 'duration_minutes': 120,
     'description': 'Coloración profesional para hombres y mujeres: tinte completo, retoque de raíz, mechas, reflejos o balayage. El precio y la duración dependen del largo del cabello y de la técnica elegida. Coordinamos cada detalle por WhatsApp para garantizarte un resultado a tu medida.',
     'features': ['Diagnóstico capilar', 'Color profesional', 'Producto premium'],
     'requires_consultation': True},
    {'name': 'Silver premium + Barba', 'slug': 'silver-premium-barba', 'price': 40000,
     'duration_minutes': 80,
     # Silver Premium (5 ítems) + ritual de barba (4 ítems) = 9 bullets.
     # Las frases se escriben sin " y " para que la regex del wizard no las parta.
     'description': 'Corte, Lavado con shampoo específico, Masaje capilar, Estilismo, Bebidas ilimitadas, Toalla caliente para preparar la piel, Diseño de barba ritual, Aceite o bálsamo hidratante, Cera fortalecedora',
     'features': [
         'Corte',
         'Lavado con shampoo específico',
         'Masaje capilar',
         'Estilismo',
         'Bebidas ilimitadas',
         'Toalla caliente para preparar la piel',
         'Diseño de barba ritual',
         'Aceite o bálsamo hidratante',
         'Cera fortalecedora',
     ]},
    {'name': 'Servicio Gold Dama', 'slug': 'servicio-gold-dama', 'price': 50000,
     'duration_minutes': 90,
     'description': 'Corte sencillo, Despunte recto en U o V, Lavado con shampoo específico, Tratamiento capilar nutritivo, Masaje capilar, Masaje cervical, Estilismo',
     'features': [
         'Corte sencillo (despunte recto, en forma de U o V)',
         'Lavado con shampoo específico',
         'Tratamiento capilar nutritivo',
         'Masaje capilar',
         'Masaje cervical',
         'Estilismo y peinado final',
     ]},
    {'name': 'Gold Exclusive', 'slug': 'gold-exclusive', 'price': 65000,
     'duration_minutes': 90, 'features': ['Corte', 'Lavado con shampoo específico', 'Masaje capilar', 'Masaje cervical', 'Estilismo', 'Arreglo de barba o diseño de cejas', 'Una (1) bebida nacional']},
    {'name': 'Servicio Diamond VIP Dama', 'slug': 'servicio-diamond-vip-dama', 'price': 70000,
     'duration_minutes': 120,
     # Espejado del Diamond VIP de hombres: "arreglo de barba" se reemplaza
     # por "hidratación profunda" (equivalente premium para cabello dama).
     'description': 'Corte sencillo, Despunte recto en U o V, Lavado con shampoo específico, Tratamiento capilar, Masaje ocular, Masaje capilar, Masaje cervical, Hidratación profunda, Estilismo, Servicio de definición opcional (valor agregado a consultar con el estilista)',
     'features': [
         'Corte sencillo (despunte recto, en U o V)',
         'Lavado con shampoo específico',
         'Tratamiento capilar',
         'Masaje ocular',
         'Masaje capilar',
         'Masaje cervical',
         'Hidratación profunda (en vez de arreglo de barba)',
         'Estilismo',
         'Servicio de definición opcional (valor agregado a consultar con el estilista)',
     ]},
    {'name': 'Diamond VIP', 'slug': 'diamond-vip', 'price': 115000,
     'duration_minutes': 120, 'features': ['Gold Exclusive', 'Beneficios Diamond']},
]

# Desactivar servicios que no están en la lista oficial
Service.objects.update(is_active=False)

for i, svc in enumerate(services_data):
    Service.objects.update_or_create(
        slug=svc['slug'],
        defaults={**svc, 'display_order': i, 'is_active': True}
    )

# Limpiar barberos de prueba si existen
Barber.objects.filter(display_name__in=['Barbero Prueba', 'Juan Pérez', 'Carlos Estilista']).delete()
User.objects.filter(username__in=['barberoprueba', 'juan', 'carlos']).delete()

# Limpiar servicios ficticios
Service.objects.filter(name__in=[
    'Corte Básico', 'Corte + Freestyle', 'Corte con Barba', 'Corte para Dama',
    'Corte Imperial', 'Ritual de Barba', 'The Club Experience', 
    'Freestyle Creativo', 'Rayitos o Mechas', 'Trenzados'
]).delete()
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

# --- Autocuración para services_service.requires_consultation ---
from apps.services.models import Service as _SvcModel
try:
    _SvcModel.objects.filter(requires_consultation=False).exists()
except Exception:
    print("⚠ Columna 'requires_consultation' no encontrada en services_service. Intentando crearla...")
    try:
        from django.db import models as _dj_models
        with connection.schema_editor() as schema_editor:
            _f = _dj_models.BooleanField(default=False)
            _f.set_attributes_from_name('requires_consultation')
            schema_editor.add_field(_SvcModel, _f)
        print("✓ Columna 'requires_consultation' creada exitosamente.")
    except Exception as _e:
        print("⚠ No se pudo crear la columna manualmente:", _e)

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

# --- Autocuración para los campos nuevos del MonthlyROISnapshot (migración 0002) ---
from apps.roi.models import MonthlyROISnapshot as _ROISnapshot

_roi_repair_fields = [
    ('gross_services', 'Ingresos por Servicios'),
    ('total_inventory_sales', 'Ingresos por Venta de Inventario'),
    ('total_fixed_expenses', 'Egresos Fijos'),
    ('total_operational_expenses', 'Egresos Operativos'),
]
try:
    # Una query que toque todas las columnas nuevas → si una falta, lanza error.
    _ROISnapshot.objects.values_list(
        'gross_services', 'total_inventory_sales',
        'total_fixed_expenses', 'total_operational_expenses',
    ).first()
except Exception:
    print("⚠ Columnas de desglose en roi_monthlyroisnapshot no encontradas. Intentando crearlas...")
    try:
        from django.db import models as _dj_models
        with connection.schema_editor() as schema_editor:
            for fname, verbose in _roi_repair_fields:
                try:
                    field = _dj_models.DecimalField(max_digits=15, decimal_places=0, default=0, verbose_name=verbose)
                    field.set_attributes_from_name(fname)
                    schema_editor.add_field(_ROISnapshot, field)
                    print(f"  ✓ Columna '{fname}' creada.")
                except Exception as inner:
                    # Probablemente ya existía — no es fatal
                    print(f"  · '{fname}': {inner}")
    except Exception as e:
        print("⚠ No se pudieron crear las columnas de ROI manualmente:", e)

# --- Autocuración para la tabla cashflow_barberadvance (vales/adelantos) ---
from apps.cashflow.models import BarberAdvance as _BarberAdvance
try:
    _BarberAdvance.objects.exists()
except Exception:
    print("⚠ Tabla 'cashflow_barberadvance' no encontrada. Intentando crearla...")
    try:
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(_BarberAdvance)
        print("✓ Tabla de BarberAdvance creada limpiamente vía Schema Editor")
    except Exception as e:
        print("⚠ No se pudo crear la tabla de BarberAdvance manualmente:", e)

# --- Normalizar duración de las citas ACTIVAS de Frank a 2h (regla de negocio) ---
# Frank ocupa siempre 2h; citas antiguas pudieron quedar con 30/60 min y eso
# permitía agendar otra cita pegada. Se corrige de forma idempotente.
try:
    from apps.bookings.models import Booking as _Bk
    from apps.barbers.models import Barber as _Barber
    _frank_ids = list(_Barber.objects.filter(display_name__icontains='frank').values_list('id', flat=True))
    if _frank_ids:
        _fixed = _Bk.objects.filter(
            barber_id__in=_frank_ids,
            status__in=['pending', 'confirmed'],
        ).exclude(duration_minutes=120).update(duration_minutes=120)
        if _fixed:
            print(f"✓ Normalizadas {_fixed} citas activas de Frank a 120 min")
except Exception as _e:
    print("⚠ No se pudo normalizar la duración de citas de Frank:", _e)

from apps.cashflow.models import PaymentMethod

pm1, _ = PaymentMethod.objects.get_or_create(slug='efectivo', defaults={'name': 'Efectivo', 'is_active': True, 'requires_reference': False})
pm2, _ = PaymentMethod.objects.get_or_create(slug='transferencia', defaults={'name': 'Transferencia (Nequi/Bancolombia)', 'is_active': True, 'requires_reference': True})

# Crear superusuarios automáticamente para Railway.
# Las contraseñas vienen de variables de entorno y SOLO se asignan al crear el
# usuario (o cuando se provee un override por env para rotarla). Nunca se
# reimponen en cada boot: si un socio cambia su clave desde el panel, el
# siguiente deploy la respeta.
import secrets as _secrets

users_to_create = [
    {'username': 'camilorf', 'env': 'SEED_CAMILO_PASSWORD', 'email': 'camilo@area30.co'},
    {'username': 'juandavid.castro', 'env': 'SEED_JUANDAVID_PASSWORD', 'email': 'juandavid@area30.co'},
    {'username': 'soporte_tecnico', 'env': 'SEED_SOPORTE_PASSWORD', 'email': 'soporte@area30.co'},
]

for user_data in users_to_create:
    try:
        uname = user_data['username']
        user, created = User.objects.get_or_create(username=uname, defaults={'email': user_data['email']})
        env_pwd = os.environ.get(user_data['env'])
        if created or env_pwd:
            # En primera creación sin env: contraseña aleatoria impresa al log
            # (el operador la rota); nunca una clave fija versionada en el repo.
            new_pwd = env_pwd or _secrets.token_urlsafe(12)
            user.set_password(new_pwd)
            if created and not env_pwd:
                print(f"⚠ Usuario {uname} creado con contraseña ALEATORIA temporal: {new_pwd} — cámbiala.")
        user.is_staff = True
        user.is_superuser = True
        user.save()
        UserProfile.objects.get_or_create(user=user, defaults={'role': 'superadmin'})
        print(f"OK: Usuario {uname} {'creado' if created else 'actualizado (clave sin cambios)'} correctamente.")
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

# Actualizar email de Samuel para notificaciones exclusivas
try:
    from apps.barbers.models import Barber
    samuel = Barber.objects.filter(display_name__icontains='samuel').first()
    if samuel and samuel.user:
        samuel.user.email = 'samuelmedf@gmail.com'
        samuel.user.save()
        print("Email de Samuel actualizado a samuelmedf@gmail.com")
except Exception as e:
    print("Error actualizando email de Samuel:", e)

# Actualizar email de Cristian para notificaciones exclusivas
try:
    from apps.barbers.models import Barber
    cristian = Barber.objects.filter(display_name__icontains='cristian').first()
    if cristian and cristian.user:
        cristian.user.email = 'cristiangome930@gmail.com'
        cristian.user.save()
        print("Email de Cristian actualizado a cristiangome930@gmail.com")
except Exception as e:
    print("Error actualizando email de Cristian:", e)
