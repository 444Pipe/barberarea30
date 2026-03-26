from rest_framework import generics
from rest_framework.permissions import AllowAny
from .models import Service
from .serializers import ServiceSerializer


class ServiceListView(generics.ListAPIView):
    """GET /api/services/ — lista pública de servicios activos."""
    queryset = Service.objects.filter(is_active=True)
    serializer_class = ServiceSerializer
    permission_classes = [AllowAny]
    pagination_class = None
