from rest_framework import serializers
from .models import Barber, GalleryImage
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
    # Write-only: credenciales personalizadas al crear
    new_username = serializers.CharField(write_only=True, required=False, allow_blank=True)
    new_password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Barber
        fields = ['id', 'display_name', 'username', 'email', 'avatar', 'phone',
                  'bio', 'specialties', 'specialty_ids', 'is_available',
                  'schedule', 'color_tag', 'total_cuts', 'rating', 'created_at',
                  'new_username', 'new_password']

    def validate(self, attrs):
        from .models import Barber
        from django.contrib.auth.models import User
        if self.instance is None:
            if Barber.objects.count() >= 8:
                raise serializers.ValidationError("Se ha alcanzado el límite máximo de 8 barberos permitidos.")
            # Validate custom username uniqueness
            new_username = attrs.get('new_username', '').strip()
            if new_username and User.objects.filter(username=new_username).exists():
                raise serializers.ValidationError({"new_username": "Ese nombre de usuario ya está en uso."})
        return super().validate(attrs)

    def create(self, validated_data):
        from django.contrib.auth.models import User
        from apps.users.models import Barbershop, UserProfile

        # 1. Determinar username y password
        display_name = validated_data.get('display_name', 'Barbero')
        custom_username = validated_data.pop('new_username', '').strip()
        custom_password = validated_data.pop('new_password', '').strip()

        if custom_username:
            username = custom_username
        else:
            # Auto-generar desde el nombre
            username = display_name.lower().replace(' ', '_')
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1

        password = custom_password if custom_password else 'area30barber'

        user = User.objects.create_user(
            username=username,
            password=password
        )

        # Guardar credenciales en el objeto para retornarlas en la view
        user._plain_password = password

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

        # 4. Create UserProfile con rol barbero
        UserProfile.objects.get_or_create(user=user, defaults={'role': 'barber'})

        # Adjuntar credenciales al barber para que la view las retorne
        barber._created_username = username
        barber._created_password = password

        return barber

    def update(self, instance, validated_data):
        specialties = validated_data.pop('specialties', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if specialties is not None:
            instance.specialties.set(specialties)
            
        return instance


class GalleryImageSerializer(serializers.ModelSerializer):
    barber_name = serializers.CharField(source='barber.display_name', read_only=True, default=None)

    class Meta:
        model = GalleryImage
        fields = ['id', 'image', 'title', 'barber', 'barber_name', 'display_order', 'created_at']


class AvailabilitySlotSerializer(serializers.Serializer):
    """Representación de un slot de tiempo disponible."""
    time = serializers.TimeField()
    available = serializers.BooleanField()
