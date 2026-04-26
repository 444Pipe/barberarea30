from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from apps.cashflow.models import Sale
from apps.users.permissions import IsOperationalAdminOrAbove

@api_view(['GET'])
@permission_classes([IsOperationalAdminOrAbove])
def pending_sales_list(request):
    """
    Lista de ventas pendientes de aprobación.
    """
    sales = Sale.objects.filter(approval_status=Sale.STATUS_PENDING).order_by('-created_at')
    data = [
        {
            'id': s.id,
            'barber': s.barber.display_name if s.barber else '',
            'service': s.service.name if s.service else '',
            'client': s.booking.client_name if s.booking else '',
            'final_price': str(s.final_price),
            'created_at': s.created_at,
        }
        for s in sales
    ]
    return Response({'pending_sales': data})
