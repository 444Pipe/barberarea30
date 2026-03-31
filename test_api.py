import os
import django
import traceback
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()

from apps.services.views import obtener_servicios_nativos
from django.test import RequestFactory

try:
    req = RequestFactory().get('/api/servicios-nativos/')
    res = obtener_servicios_nativos(req)
    print("SUCCESS")
    print(res.content)
except Exception as e:
    traceback.print_exc(file=sys.stdout)
