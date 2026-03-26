from rest_framework import serializers
from .models import Booking


class BookingCreateSerializer(serializers.ModelSerializer):
    """Serializer público para crear reservas."""
    service_id = serializers.IntegerField(write_only=True)
    barber_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = Booking
        fields = ['id', 'client_name', 'client_phone', 'client_email',
                  'barber_id', 'service_id', 'date', 'time', 'notes', 'price',
                  'status', 'created_at']
        read_only_fields = ['id', 'status', 'created_at']


class BookingAdminSerializer(serializers.ModelSerializer):
    """Serializer completo para el admin."""
    barber_name = serializers.CharField(source='barber.display_name', read_only=True)
    barber_color = serializers.CharField(source='barber.color_tag', read_only=True)
    service_name = serializers.CharField(source='service.name', read_only=True)

    class Meta:
        model = Booking
        fields = ['id', 'client_name', 'client_phone', 'client_email',
                  'barber', 'barber_name', 'barber_color',
                  'service', 'service_name',
                  'date', 'time', 'duration_minutes', 'status',
                  'notes', 'price', 'created_at', 'updated_at', 'completed_at']
