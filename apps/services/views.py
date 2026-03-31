from rest_framework import generics
from rest_framework.permissions import AllowAny
from django.http import JsonResponse
from .models import Service
from .serializers import ServiceSerializer


class ServiceListView(generics.ListAPIView):
    """GET /api/services/ — lista pública de servicios activos."""
    queryset = Service.objects.filter(is_active=True)
    serializer_class = ServiceSerializer
    permission_classes = [AllowAny]
    pagination_class = None

def obtener_servicios_nativos(request):
    """Endpoint nativo de servicios para JS Vanilla"""
    servicios = list(Service.objects.filter(is_active=True).values('id', 'name', 'price', 'duration_minutes'))
    return JsonResponse({'servicios': servicios}, safe=False)
