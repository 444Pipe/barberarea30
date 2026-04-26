from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.contrib.auth.models import User
from apps.cashflow.models import Sale
from apps.users.permissions import IsOperationalAdminOrAbove

@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def approve_sale(request, sale_id):
    """
    Aprueba una venta pendiente.
    """
    try:
        sale = Sale.objects.get(id=sale_id)
    except Sale.DoesNotExist:
        return Response({'error': 'Venta no encontrada'}, status=status.HTTP_404_NOT_FOUND)
    if sale.approval_status != Sale.STATUS_PENDING:
        return Response({'error': 'La venta ya fue procesada'}, status=status.HTTP_400_BAD_REQUEST)
    sale.approval_status = Sale.STATUS_APPROVED
    sale.approved_by = request.user
    sale.approved_at = timezone.now()
    sale.save(update_fields=['approval_status', 'approved_by', 'approved_at'])
    return Response({'message': 'Venta aprobada correctamente'})

@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def reject_sale(request, sale_id):
    """
    Rechaza una venta pendiente.
    """
    reason = request.data.get('reason', '')
    try:
        sale = Sale.objects.get(id=sale_id)
    except Sale.DoesNotExist:
        return Response({'error': 'Venta no encontrada'}, status=status.HTTP_404_NOT_FOUND)
    if sale.approval_status != Sale.STATUS_PENDING:
        return Response({'error': 'La venta ya fue procesada'}, status=status.HTTP_400_BAD_REQUEST)
    sale.approval_status = Sale.STATUS_REJECTED
    sale.rejected_by = request.user
    sale.rejected_at = timezone.now()
    sale.rejection_reason = reason
    sale.save(update_fields=['approval_status', 'rejected_by', 'rejected_at', 'rejection_reason'])
    return Response({'message': 'Venta rechazada correctamente'})
