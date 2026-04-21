import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()

from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User

user = User.objects.filter(is_superuser=True).first()
if not user:
    user = User.objects.create_superuser('testadmin', 'test@test.com', 'test')

client = Client()
client.force_login(user)

img = SimpleUploadedFile("test.jpg", b"file_content", content_type="image/jpeg")
response = client.post('/api/admin/inventory/items/create/', {
    'name': 'Test Cola',
    'category': 'beverage',
    'sale_price': '2000',
    'cost_per_unit': '1000',
    'minimum_stock': '5',
    'image': img
})

print("Status:", response.status_code)
if response.status_code == 500:
    print(response.content.decode('utf-8')[:2000])
else:
    print("Content:", response.json())
