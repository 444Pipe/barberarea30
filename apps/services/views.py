import logging

from rest_framework import generics
from rest_framework.permissions import AllowAny
from django.http import JsonResponse
from .models import Service
from .serializers import ServiceSerializer

logger = logging.getLogger(__name__)


from django.utils.text import slugify
from apps.users.permissions import IsSuperAdminOrReadOnly

class ServiceListView(generics.ListCreateAPIView):
    """GET /api/services/ — lista pública, POST crea nuevo servicio (solo superadmin)."""
    queryset = Service.objects.filter(is_active=True).order_by('price')
    serializer_class = ServiceSerializer
    permission_classes = [IsSuperAdminOrReadOnly]
    pagination_class = None

    def perform_create(self, serializer):
        name = serializer.validated_data.get('name', '')
        base_slug = slugify(name)
        slug = base_slug
        counter = 1
        while Service.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        
        serializer.save(slug=slug)


class ServiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PUT/DELETE /api/services/{id}/ — escritura solo superadmin."""
    queryset = Service.objects.filter(is_active=True)
    serializer_class = ServiceSerializer
    permission_classes = [IsSuperAdminOrReadOnly]

from django.core.serializers.json import DjangoJSONEncoder

def obtener_servicios_nativos(request):
    """Endpoint nativo de servicios para JS Vanilla"""
    try:
        servicios = list(Service.objects.filter(is_active=True).order_by('price').values(
            'id', 'name', 'price', 'duration_minutes', 'description',
            'exclusive_barber_id', 'requires_consultation',
        ))
        return JsonResponse({'servicios': servicios}, safe=False, encoder=DjangoJSONEncoder)
    except Exception:
        logger.exception('Error al obtener los servicios nativos')
        return JsonResponse({'error': 'No se pudieron obtener los servicios.'}, status=500)
