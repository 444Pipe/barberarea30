import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
os.environ['CLOUDINARY_URL'] = 'cloudinary://a:b@c'
django.setup()

from django.core.management import call_command
try:
    call_command('migrate', interactive=False)
except Exception as e:
    print("Migration error:", e)

from django.test import Client
from django.contrib.auth import get_user_model
from apps.inventory.models import InventoryItem
from apps.users.models import UserProfile

User = get_user_model()
user = User.objects.filter(is_superuser=True).first()
if not user:
    user = User.objects.create_superuser('testadmin', 'test@test.com', 'test')

profile, _ = UserProfile.objects.get_or_create(user=user, defaults={'role': 'superadmin'})

# Make sure we have an item
item = InventoryItem.objects.first()
if not item:
    item = InventoryItem.objects.create(name="Aguila Test", category="beverage", quantity=0)

client = Client()
client.force_login(user)

print("Testing adjust for item:", item.name)

response = client.post(f'/api/admin/inventory/{item.id}/adjust/', {
    'type': 'add',
    'quantity': 15,
    'notes': 'Nuevo surtido'
}, content_type='application/json')

print("Status:", response.status_code)
if response.status_code == 500:
    print(response.content.decode('utf-8')[:2000])
else:
    print("Content:", response.json())
