from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.views import APIView
from django.views.decorators.csrf import csrf_exempt

from apps.users.permissions import IsOperationalAdminOrAbove, IsBarberOrAbove
from apps.analytics.models import log_audit
from apps.inventory.models import InventoryItem, InventoryMovement


# ─── LIST & CREATE ────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsBarberOrAbove])
def inventory_list_view(request):
    """GET /api/admin/inventory/items/ — Lista todos los productos activos."""
    items = InventoryItem.objects.filter(is_active=True).order_by('category', 'name')
    data = []
    for item in items:
        data.append({
            'id': item.id,
            'name': item.name,
            'category': item.category,
            'category_display': item.get_category_display(),
            'description': item.description,
            'image': request.build_absolute_uri(item.image.url) if item.image else None,
            'unit': item.unit,
            'quantity': float(item.quantity),
            'minimum_stock': float(item.minimum_stock),
            'cost_per_unit': float(item.cost_per_unit),
            'sale_price': float(item.sale_price),
            'is_low_stock': item.is_low_stock,
        })
    return Response(data)


@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def inventory_create_view(request):
    """POST /api/admin/inventory/items/create/ — Crea un nuevo producto."""
    name = request.data.get('name', '').strip()
    category = request.data.get('category', 'other')
    description = request.data.get('description', '').strip()
    unit = request.data.get('unit', 'unidad').strip()
    minimum_stock = request.data.get('minimum_stock', 5)
    cost_per_unit = request.data.get('cost_per_unit', 0)
    sale_price = request.data.get('sale_price', 0)
    image = request.FILES.get('image')

    if not name:
        return Response({'error': 'El nombre del producto es obligatorio.'}, status=400)

    try:
        cost_per_unit = float(cost_per_unit)
        sale_price = float(sale_price)
        minimum_stock = float(minimum_stock)
    except (TypeError, ValueError):
        return Response({'error': 'Valores numéricos inválidos.'}, status=400)

    try:
        item = InventoryItem.objects.create(
            name=name,
            category=category,
            description=description,
            unit=unit,
            minimum_stock=minimum_stock,
            cost_per_unit=cost_per_unit,
            sale_price=sale_price,
            image=image,
        )
    except Exception as e:
        msg = str(e)
        if "api_key" in msg.lower() or "cloudinary" in msg.lower() or "must supply" in msg.lower():
            return Response({'error': 'Configuración de Cloudinary incompleta. Faltan variables de entorno en Railway.'}, status=500)
        elif "column" in msg.lower() or "relation" in msg.lower():
            return Response({'error': 'Falta ejecutar las migraciones en tu entorno de producción (Railway).'}, status=500)
        return Response({'error': f'Error interno: {msg}'}, status=500)

    log_audit(
        user=request.user,
        action='create',
        obj=item,
        changes={'name': name, 'category': category, 'sale_price': str(sale_price)},
        request=request,
        extra_data={'msg': f'Creó el producto de inventario: {name}'}
    )

    return Response({'ok': True, 'id': item.id, 'name': item.name}, status=201)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsOperationalAdminOrAbove])
def inventory_update_view(request, item_id):
    """PUT /api/admin/inventory/items/<id>/update/ — Edita un producto."""
    try:
        item = InventoryItem.objects.get(id=item_id, is_active=True)
    except InventoryItem.DoesNotExist:
        return Response({'error': 'Producto no encontrado.'}, status=404)

    data = request.data
    item.name = data.get('name', item.name).strip() or item.name
    item.category = data.get('category', item.category)
    item.description = data.get('description', item.description)
    item.unit = data.get('unit', item.unit).strip() or item.unit
    item.minimum_stock = float(data.get('minimum_stock', item.minimum_stock))
    item.cost_per_unit = float(data.get('cost_per_unit', item.cost_per_unit))
    item.sale_price = float(data.get('sale_price', item.sale_price))

    if 'image' in request.FILES:
        item.image = request.FILES['image']

    try:
        item.save()
    except Exception as e:
        msg = str(e)
        if "api_key" in msg.lower() or "cloudinary" in msg.lower() or "must supply" in msg.lower():
            return Response({'error': 'Configuración de Cloudinary incompleta. Faltan variables de entorno en Railway.'}, status=500)
        elif "column" in msg.lower() or "relation" in msg.lower():
            return Response({'error': 'Falta ejecutar las migraciones en tu entorno de producción (Railway).'}, status=500)
        return Response({'error': f'Error interno: {msg}'}, status=500)

    log_audit(
        user=request.user,
        action='update',
        obj=item,
        changes={
            'name': item.name,
            'sale_price': str(item.sale_price),
            'cost_per_unit': str(item.cost_per_unit),
        },
        request=request,
        extra_data={'msg': f'Editó el producto: {item.name}'}
    )

    return Response({'ok': True, 'message': 'Producto actualizado.'})


@api_view(['DELETE'])
@permission_classes([IsOperationalAdminOrAbove])
def inventory_delete_view(request, item_id):
    """DELETE /api/admin/inventory/items/<id>/delete/ — Desactiva un producto (soft delete)."""
    try:
        item = InventoryItem.objects.get(id=item_id, is_active=True)
    except InventoryItem.DoesNotExist:
        return Response({'error': 'Producto no encontrado.'}, status=404)

    item.is_active = False
    item.save()

    log_audit(
        user=request.user,
        action='delete',
        obj=item,
        changes={},
        request=request,
        extra_data={'msg': f'Desactivó el producto de inventario: {item.name}'}
    )

    return Response({'ok': True, 'message': f'Producto "{item.name}" desactivado.'})


# ─── AJUSTE DE STOCK ──────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def adjust_inventory_view(request, item_id):
    """POST /api/admin/inventory/<id>/adjust/ - Ajuste manual de stock."""
    try:
        item = InventoryItem.objects.get(id=item_id, is_active=True)
    except InventoryItem.DoesNotExist:
        return Response({'error': 'Producto no encontrado.'}, status=404)

    data = request.data
    adjustment_type = data.get('type')  # 'add' or 'subtract'
    quantity_change = data.get('quantity')
    notes = data.get('notes', '').strip()

    if adjustment_type not in ['add', 'subtract'] or not quantity_change:
        return Response({'error': 'Tipo de ajuste y cantidad son requeridos.'}, status=400)

    try:
        quantity_change = float(quantity_change)
        if quantity_change <= 0:
            raise ValueError
    except ValueError:
        return Response({'error': 'Cantidad inválida.'}, status=400)

    qty_before = float(item.quantity)

    if adjustment_type == 'add':
        item.quantity = qty_before + quantity_change
        movement_type = 'purchase' if 'compra' in notes.lower() else 'adjustment'
    else:
        if qty_before < quantity_change:
            return Response({'error': 'No hay suficiente stock para descontar esa cantidad.'}, status=400)
        item.quantity = qty_before - quantity_change
        movement_type = 'waste' if 'merma' in notes.lower() or 'desperdicio' in notes.lower() else 'adjustment'

    item.save()

    InventoryMovement.objects.create(
        item=item,
        movement_type=movement_type,
        quantity=quantity_change,
        quantity_before=qty_before,
        quantity_after=item.quantity,
        performed_by=request.user,
        notes=notes
    )

    action_word = "Añadió" if adjustment_type == 'add' else "Restó"
    log_audit(
        user=request.user,
        action='inventory',
        obj=item,
        changes={'qty_before': str(qty_before), 'qty_after': str(item.quantity)},
        request=request,
        extra_data={'msg': f"{action_word} {quantity_change} {item.unit} a {item.name}. Razón: {notes}"}
    )

    return Response({
        'ok': True,
        'message': 'Inventario actualizado correctamente.',
        'new_quantity': float(item.quantity)
    })


# ─── CONSUMIBLES PARA CHECKOUT (vista del barbero) ───────────────────────────

@api_view(['GET'])
@permission_classes([IsBarberOrAbove])
def consumables_for_checkout_view(request):
    """
    GET /api/admin/inventory/consumables/
    Retorna bebidas y consumibles disponibles para que el barbero seleccione
    cuáles se consumieron durante el corte al hacer checkout.
    """
    items = InventoryItem.objects.filter(
        is_active=True,
        quantity__gt=0,
        category__in=['beverage', 'consumable', 'other']
    ).order_by('category', 'name')

    data = []
    for item in items:
        data.append({
            'id': item.id,
            'name': item.name,
            'category': item.category,
            'category_display': item.get_category_display(),
            'unit': item.unit,
            'sale_price': float(item.sale_price),
            'quantity_available': float(item.quantity),
            'image': request.build_absolute_uri(item.image.url) if item.image else None,
        })

    return Response(data)


@api_view(['POST'])
@permission_classes([IsBarberOrAbove])
def register_consumables_view(request, booking_id):
    """
    POST /api/admin/inventory/consumables/<booking_id>/
    Registra los consumibles usados en un corte (desde el perfil del barbero).
    Body: { "items": [{"id": 1, "qty": 2}, {"id": 3, "qty": 1}] }
    """
    from apps.bookings.models import Booking
    from apps.inventory.models import InventoryItem, InventoryMovement
    from django.db import transaction

    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        return Response({'error': 'Reserva no encontrada.'}, status=404)

    items_data = request.data.get('items', [])
    if not items_data:
        return Response({'error': 'No se enviaron consumibles.'}, status=400)

    total_consumable_value = 0

    with transaction.atomic():
        for entry in items_data:
            item_id = entry.get('id')
            qty = float(entry.get('qty', 1))

            try:
                item = InventoryItem.objects.get(id=item_id, is_active=True)
            except InventoryItem.DoesNotExist:
                continue

            qty_before = float(item.quantity)
            qty_after = max(0, qty_before - qty)
            item.quantity = qty_after
            item.save()

            InventoryMovement.objects.create(
                item=item,
                movement_type='out',
                quantity=qty,
                quantity_before=qty_before,
                quantity_after=qty_after,
                booking=booking,
                performed_by=request.user,
                notes=f'Consumo en corte — {booking.client_name}'
            )

            total_consumable_value += float(item.sale_price) * qty

        log_audit(
            user=request.user,
            action='inventory',
            obj=booking,
            changes={'consumables': str(items_data), 'total_value': str(total_consumable_value)},
            request=request,
            extra_data={
                'msg': (
                    f'Registró consumibles para el corte de {booking.client_name} '
                    f'— Valor total: ${total_consumable_value:,.0f}'
                )
            }
        )

    return Response({
        'ok': True,
        'message': 'Consumibles registrados correctamente.',
        'total_value': float(total_consumable_value)
    })
