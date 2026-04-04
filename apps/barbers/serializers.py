from rest_framework import serializers
from .models import Barber
from apps.services.serializers import ServiceSerializer


class BarberListSerializer(serializers.ModelSerializer):
    """Serializer público para lista de barberos activos."""
    specialties = ServiceSerializer(many=True, read_only=True)

    class Meta:
        model = Barber
        fields = ['id', 'display_name', 'avatar', 'bio', 'specialties',
                  'is_available', 'color_tag', 'total_cuts', 'rating']


class BarberAdminSerializer(serializers.ModelSerializer):
    """Serializer completo para administración."""
    specialties = ServiceSerializer(many=True, read_only=True)
    specialty_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, source='specialties',
        queryset=__import__('apps.services.models', fromlist=['Service']).Service.objects.all(),
        required=False
    )
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = Barber
        fields = ['id', 'display_name', 'username', 'email', 'avatar', 'phone',
                  'bio', 'specialties', 'specialty_ids', 'is_available',
                  'schedule', 'color_tag', 'total_cuts', 'rating', 'created_at']

    def validate(self, attrs):
        from .models import Barber
        if self.instance is None:
            if Barber.objects.count() >= 8:
                raise serializers.ValidationError("Se ha alcanzado el límite máximo de 8 barberos permitidos.")
        return super().validate(attrs)

    def create(self, validated_data):
        from django.contrib.auth.models import User
        from apps.users.models import Barbershop, UserProfile

        # 1. Create a dummy User for the barber if not provided
        display_name = validated_data.get('display_name', 'Barbero')
        username = display_name.lower().replace(' ', '_')
        
        # Ensure unique username
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1
            
        from django.utils.crypto import get_random_string
        
        user = User.objects.create_user(
            username=username,
            password='area30barber'
        )
        
        # 2. Assign default Barbershop
        barbershop = Barbershop.objects.first()
        if not barbershop:
            barbershop = Barbershop.objects.create(name="Área 30 Barber Club")

        # 3. Save Barber
        specialties = validated_data.pop('specialties', [])
        barber = Barber.objects.create(
            user=user,
            barbershop=barbershop,
            **validated_data
        )
        
        if specialties:
            barber.specialties.set(specialties)

        # 4. Optional: Create a UserProfile for role management
        UserProfile.objects.get_or_create(user=user, role='barber')
            
        return barber

    def update(self, instance, validated_data):
        specialties = validated_data.pop('specialties', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if specialties is not None:
            instance.specialties.set(specialties)
            
        return instance


class AvailabilitySlotSerializer(serializers.Serializer):
    """Representación de un slot de tiempo disponible."""
    time = serializers.TimeField()
    available = serializers.BooleanField()
