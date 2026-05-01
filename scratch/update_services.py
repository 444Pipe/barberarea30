from apps.services.models import Service
import re

count = 0
for s in Service.objects.all():
    updated = False
    if 'arreglo' in s.name.lower():
        s.name = re.sub('arreglo', 'Diseño', s.name, flags=re.IGNORECASE)
        updated = True
    if 'arreglo' in s.description.lower():
        s.description = re.sub('arreglo', 'Diseño', s.description, flags=re.IGNORECASE)
        updated = True
    # Also check features (JSONField)
    if s.features:
        new_features = []
        for f in s.features:
            if 'arreglo' in f.lower():
                new_features.append(re.sub('arreglo', 'Diseño', f, flags=re.IGNORECASE))
                updated = True
            else:
                new_features.append(f)
        s.features = new_features
        
    if updated:
        s.save()
        count += 1
        print(f"Updated: {s.name}")

print(f"Total services updated in DB: {count}")
