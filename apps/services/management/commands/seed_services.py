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
        services_data = [
            {'name': 'Corte Imperial', 'slug': 'corte-imperial', 'price': 30000,
             'duration_minutes': 30, 'features': ['Asesoría visajista', 'Precisión milimétrica', 'Acabado impecable']},
            {'name': 'Corte + Freestyle', 'slug': 'corte-freestyle', 'price': 35000,
             'duration_minutes': 40, 'features': ['Corte completo', 'Diseño freestyle personalizado', 'Cejas y styling'],
             'is_popular': True},
            {'name': 'Corte con Barba', 'slug': 'corte-barba', 'price': 40000,
             'duration_minutes': 40, 'features': ['Corte de cabello', 'Perfilado de barba', 'Cejas y styling']},
            {'name': 'The Club Experience', 'slug': 'club-experience', 'price': 60000,
             'duration_minutes': 60, 'features': ['Corte imperial', 'Arreglo de barba ritual', 'Vapor ozono', 'Mascarilla'],
             'is_popular': True},
            {'name': 'Ritual de Barba', 'slug': 'ritual-barba', 'price': 25000,
             'duration_minutes': 30, 'features': ['Perfilación a navaja', 'Toallas calientes aromáticas', 'Aceites premium']},
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
        self.stdout.write(self.style.SUCCESS(f'✓ {len(services_data)} servicios creados/actualizados'))

        # ─── Barbershop ──────────────────────────
        shop, created = Barbershop.objects.get_or_create(
            name='Área 30 Barber Club',
            defaults={
                'address': 'C.C. Sunrise, Restrepo - Meta, Colombia',
                'phone': '+57 312 487 9250',
                'whatsapp': '573124879250',
                'instagram': '@area30barberclub',
                'tiktok': '@area30barberclub',
            }
        )
        action = 'creada' if created else 'ya existía'
        self.stdout.write(self.style.SUCCESS(f'✓ Barbería "{shop.name}" {action}'))

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
            f'✓ Usuario admin {"creado (pass: admin123)" if created else "ya existía"}'
        ))

        self.stdout.write(self.style.SUCCESS('\n✓ Seed completado exitosamente'))
