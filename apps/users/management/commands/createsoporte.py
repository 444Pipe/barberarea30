from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.users.models import UserProfile

class Command(BaseCommand):
    help = 'Creates a soporte tecnico user with full superadmin privileges.'

    def handle(self, *args, **options):
        username = 'soporte_tecnico'
        email = 'soporte@area30.com'
        password = 'Area30Soporte!' # It can be changed later

        # Delete existing if any, to ensure it gets recreated cleanly
        if User.objects.filter(username=username).exists():
            user = User.objects.get(username=username)
            self.stdout.write(self.style.WARNING(f'User {username} already exists. Updating password and permissions...'))
            user.set_password(password)
            user.is_superuser = True
            user.is_staff = True
            user.save()
        else:
            user = User.objects.create_superuser(
                username=username,
                email=email,
                password=password
            )
            self.stdout.write(self.style.SUCCESS(f'User {username} created successfully.'))

        # Ensure UserProfile exists and has superadmin role
        profile, created = UserProfile.objects.get_or_create(user=user)
        profile.role = 'superadmin'
        profile.save()

        self.stdout.write(self.style.SUCCESS(f'--- CREATION COMPLETE ---'))
        self.stdout.write(self.style.SUCCESS(f'Username: {username}'))
        self.stdout.write(self.style.SUCCESS(f'Password: {password}'))
        self.stdout.write(self.style.SUCCESS(f'Role: superadmin'))
