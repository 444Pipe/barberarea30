from rest_framework import generics
from rest_framework.permissions import AllowAny
from django.http import JsonResponse
from .models import Service
from .serializers import ServiceSerializer


from django.utils.text import slugify
from rest_framework.permissions import IsAuthenticatedOrReadOnly

class ServiceListView(generics.ListCreateAPIView):
    """GET /api/services/ — lista pública, POST crea nuevo servicio."""
    queryset = Service.objects.filter(is_active=True)
    serializer_class = ServiceSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
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

from django.core.serializers.json import DjangoJSONEncoder

def obtener_servicios_nativos(request):
    """Endpoint nativo de servicios para JS Vanilla"""
    try:
        servicios = list(Service.objects.filter(is_active=True).values('id', 'name', 'price', 'duration_minutes'))
        return JsonResponse({'servicios': servicios}, safe=False, encoder=DjangoJSONEncoder)
    except Exception as e:
        import traceback
        return JsonResponse({'error': str(e), 'trace': traceback.format_exc()}, status=500)
