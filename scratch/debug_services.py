from apps.services.models import Service
for s in Service.objects.all():
    print(f"--- {s.name} ---")
    print(f"Description: {s.description}")
    print(f"Features: {s.features}")
