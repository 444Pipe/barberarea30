"""Seed services, barbershop, and default admin user."""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from apps.services.models import Service
from apps.users.models import Barbershop, UserProfile
from apps.barbers.models import Barber


class Command(BaseCommand):
    help = 'Seed initial data: services, barbershop, and default admin user'

    def handle(self, *args, **options):
        # ─── Services ──────────────────────────
        # Color va en posición 4 para que aparezca en la primera o segunda
        # fila visible del wizard, no enterrado al fondo de la grilla.
        services_data = [
            {'name': 'Diseño de cejas', 'slug': 'diseno-de-cejas', 'price': 5000,
             'duration_minutes': 15, 'features': []},
            {'name': 'Diseño de barba', 'slug': 'diseno-de-barba', 'price': 15000,
             'duration_minutes': 20, 'features': []},
            {'name': 'Silver Premium', 'slug': 'silver-premium', 'price': 30000,
             'duration_minutes': 60, 'features': ['Corte', 'Lavado con shampoo específico', 'Masaje capilar', 'Estilismo', 'Bebidas ilimitadas']},
            {'name': 'Servicio Silver Dama', 'slug': 'servicio-silver-dama', 'price': 35000,
             'duration_minutes': 60, 'features': ['Corte sencillo', 'Despunte recto', 'En forma de U o V']},
            # ─── Color a consulta — hombres y mujeres ──────────────────────
            # Precio variable según largo y producto; el cliente DEBE escribir
            # por WhatsApp para acordar antes de reservar. requires_consultation
            # hace que el botón abra wa.me en lugar del wizard.
            {'name': 'Color', 'slug': 'color-cabello',
             'category': 'vip', 'price': 0, 'duration_minutes': 120,
             'description': 'Color para hombres y mujeres. Precio y tiempo según largo y producto. A consulta — escríbenos por WhatsApp.',
             'features': ['Diagnóstico capilar', 'Color profesional', 'Producto premium'],
             'requires_consultation': True},
            {'name': 'Silver premium + Barba', 'slug': 'silver-premium-barba', 'price': 40000,
             'duration_minutes': 80, 'features': ['Silver Premium', 'Diseño de barba ritual']},
            {'name': 'Servicio Gold Dama', 'slug': 'servicio-gold-dama', 'price': 50000,
             'duration_minutes': 90, 'features': ['Corte sencillo', 'Despunte recto', 'En forma de U o V', 'Shampoo', 'Tratamiento', 'Masaje capilar']},
            {'name': 'Gold Exclusive', 'slug': 'gold-exclusive', 'price': 65000,
             'duration_minutes': 90, 'features': ['Corte', 'Lavado con shampoo específico', 'Masaje capilar', 'Masaje cervical', 'Estilismo', 'Arreglo de barba o diseño de cejas', 'Una (1) bebida nacional']},
            {'name': 'Servicio Diamond VIP Dama', 'slug': 'servicio-diamond-vip-dama', 'price': 70000,
             'duration_minutes': 120, 'features': ['Servicio Gold Dama', 'Tratamientos extra']},
            {'name': 'Diamond VIP', 'slug': 'diamond-vip', 'price': 115000,
             'duration_minutes': 120, 'features': ['Gold Exclusive', 'Beneficios Diamond']},
        ]

        # Deactivate all existing services first
        Service.objects.update(is_active=False)

        for i, svc in enumerate(services_data):
            Service.objects.update_or_create(
                slug=svc['slug'],
                defaults={**svc, 'display_order': i, 'is_active': True}
            )
        self.stdout.write(self.style.SUCCESS(f'OK {len(services_data)} servicios sincronizados y activos. Los demás fueron desactivados.'))

        # ─── Barbershop ──────────────────────────
        shop, created = Barbershop.objects.get_or_create(
            name='Área 30 Barber Club',
            defaults={
                'address': 'C.C. Sunrise, Restrepo - Meta, Colombia',
                'phone': '+57 312 487 9250',
                'whatsapp': '573112651032',
                'instagram': '@area30barberclub',
                'tiktok': '@area30barberclub',
            }
        )
        action = 'creada' if created else 'ya existía'
        self.stdout.write(self.style.SUCCESS(f'OK Barbería "{shop.name}" {action}'))

        # ─── Admin User ──────────────────────────
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'first_name': 'Admin',
                'last_name': 'Área 30',
                'email': 'admin@area30.co',
                'is_staff': True,
            }
        )
        if created:
            admin_user.set_password('admin123')
            admin_user.save()

        UserProfile.objects.update_or_create(
            user=admin_user,
            defaults={
                'role': 'superadmin',
                'barbershop': shop,
                'phone': '+57 312 487 9250',
            }
        )
        self.stdout.write(self.style.SUCCESS(
            f'OK Usuario admin {"creado (pass: admin123)" if created else "ya existía"}'
        ))

        self.stdout.write(self.style.SUCCESS('\nOK Seed completado exitosamente'))
