from rest_framework import serializers
from .models import Booking, BlockedDate, Review


class BookingCreateSerializer(serializers.ModelSerializer):
    """Serializer público para crear reservas."""
    service_id = serializers.IntegerField(write_only=True)
    # barber_id = serializers.CharField(write_only=True, allow_blank=True, required=False) # can be 'any' or an ID
    
    class Meta:
        model = Booking
        fields = ['id', 'client_name', 'client_phone', 'client_email',
                  'barber', 'service_id', 'date', 'time', 'notes', 'price',
                  'status', 'created_at', 'is_walk_in', 'privacy_accepted']
        read_only_fields = ['id', 'status', 'created_at', 'barber']

    def validate(self, data):
        # Si no es walk-in, requiere aceptar privacidad
        if not data.get('is_walk_in') and not data.get('privacy_accepted'):
            raise serializers.ValidationError({"privacy_accepted": "Debe aceptar el tratamiento de datos personales."})
        return data


class BookingAdminSerializer(serializers.ModelSerializer):
    """Serializer completo para el admin."""
    barber_name = serializers.CharField(source='barber.display_name', read_only=True)
    barber_color = serializers.CharField(source='barber.color_tag', read_only=True)
    service_name = serializers.CharField(source='service.name', read_only=True)

    class Meta:
        model = Booking
        fields = ['id', 'client_name', 'client_phone', 'client_email',
                  'barber', 'barber_name', 'barber_color',
                  'service', 'service_name', 'is_walk_in', 'privacy_accepted',
                  'date', 'time', 'duration_minutes', 'status',
                  'notes', 'price', 'manual_labor_cost', 'manual_materials_cost', 
                  'created_at', 'updated_at', 'completed_at', 'can_cancel']


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = '__all__'


class BlockedDateSerializer(serializers.ModelSerializer):
    """Serializer para fechas bloqueadas."""
    class Meta:
        model = BlockedDate
        fields = '__all__'
