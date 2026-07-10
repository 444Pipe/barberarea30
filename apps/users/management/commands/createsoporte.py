import os
import secrets

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.users.models import UserProfile

class Command(BaseCommand):
    help = 'Creates a soporte tecnico user with full superadmin privileges.'

    def handle(self, *args, **options):
        username = 'soporte'
        email = 'soporte@area30.com'
        # La contraseña viene de SOPORTE_PASSWORD. Solo se asigna al crear el
        # usuario o cuando se provee un override por env — no se reimpone en
        # cada ejecución. Sin env y en primera creación se genera aleatoria.
        env_pwd = os.environ.get('SOPORTE_PASSWORD')

        user = User.objects.filter(username=username).first()
        created = user is None
        assigned_password = None

        if created:
            assigned_password = env_pwd or secrets.token_urlsafe(12)
            user = User.objects.create_superuser(
                username=username, email=email, password=assigned_password
            )
            self.stdout.write(self.style.SUCCESS(f'User {username} created successfully.'))
        else:
            self.stdout.write(self.style.WARNING(f'User {username} already exists.'))
            if env_pwd:
                user.set_password(env_pwd)
                assigned_password = env_pwd
            user.is_superuser = True
            user.is_staff = True
            user.save()

        # Ensure UserProfile exists and has superadmin role
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = 'superadmin'
        profile.save()

        self.stdout.write(self.style.SUCCESS('--- CREATION COMPLETE ---'))
        self.stdout.write(self.style.SUCCESS(f'Username: {username}'))
        if assigned_password:
            self.stdout.write(self.style.SUCCESS(f'Password: {assigned_password}'))
        else:
            self.stdout.write(self.style.SUCCESS('Password: (sin cambios)'))
        self.stdout.write(self.style.SUCCESS('Role: superadmin'))
