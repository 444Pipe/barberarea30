from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from apps.users.permissions import IsOperationalAdminOrAbove
from apps.analytics.models import log_audit
from apps.inventory.models import InventoryItem, InventoryMovement

@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def adjust_inventory_view(request, item_id):
    """POST /api/admin/inventory/<id>/adjust/ - Ajuste manual de stock."""
    try:
        item = InventoryItem.objects.get(id=item_id, is_active=True)
    except InventoryItem.DoesNotExist:
        return Response({'error': 'Producto no encontrado.'}, status=404)

    data = request.data
    adjustment_type = data.get('type') # 'add' or 'subtract'
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

    movement = InventoryMovement.objects.create(
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
        action='inventory_update',
        obj=item,
        changes={'qty_before': str(qty_before), 'qty_after': str(item.quantity)},
        request=request,
        extra_data={'msg': f"{action_word} {quantity_change} {item.unit} a {item.name}. Razón: {notes}"}
    )

    return Response({
        'ok': True,
        'message': 'Inventario actualizado correctamente.',
        'new_quantity': item.quantity
    })
