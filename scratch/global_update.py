from django.apps import apps
import re

for model in apps.get_models():
    try:
        # Only check models with char or text fields
        fields = [f.name for f in model._meta.fields if f.get_internal_type() in ['CharField', 'TextField', 'JSONField']]
        if not fields:
            continue
            
        for obj in model.objects.all():
            updated = False
            for field_name in fields:
                val = getattr(obj, field_name)
                if val and isinstance(val, str) and 'arreglo' in val.lower():
                    new_val = re.sub('arreglo', 'Diseño', val, flags=re.IGNORECASE)
                    setattr(obj, field_name, new_val)
                    updated = True
                    print(f"Updated {model.__name__} (pk={obj.pk}) field {field_name}: {val} -> {new_val}")
                elif val and isinstance(val, list):
                    new_list = []
                    list_updated = False
                    for item in val:
                        if isinstance(item, str) and 'arreglo' in item.lower():
                            new_item = re.sub('arreglo', 'Diseño', item, flags=re.IGNORECASE)
                            new_list.append(new_item)
                            list_updated = True
                        else:
                            new_list.append(item)
                    if list_updated:
                        setattr(obj, field_name, new_list)
                        updated = True
                        print(f"Updated {model.__name__} (pk={obj.pk}) field {field_name} (list)")
            if updated:
                obj.save()
    except Exception as e:
        # Some models might not be queryable or have other issues
        pass

print("Global DB update finished.")
