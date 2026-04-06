from rest_framework import serializers
from .models import Service


class ServiceSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(read_only=True)
    
    class Meta:
        model = Service
        fields = ['id', 'name', 'slug', 'description', 'price',
                  'duration_minutes', 'features', 'is_popular']
