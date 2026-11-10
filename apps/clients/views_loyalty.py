"""API de la tarjeta de sellos (prueba, nov-2026) — solo panel.

Ver: admin y superiores. Canjear: quien confirma ventas (operativo y
superadmin). Cambiar reglas y deshacer un canje: solo superadmin.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.services.models import Service
from apps.users.permissions import IsAdminOrAbove, IsOperationalAdminOrAbove, IsSuperAdmin

from .loyalty import build_card, build_cards, phone_key, settings_dict
from .models import LoyaltyRedemption, LoyaltySettings

CARD_ROW_FIELDS = ('phone', 'name', 'active', 'required', 'complete', 'missing', 'next_expiry', 'last_visit')


def _expires_soon(card, today, days=30):
    return bool(card['active'] and card['next_expiry']
                and (date.fromisoformat(card['next_expiry']) - today).days <= days)


@api_view(['GET'])
@permission_classes([IsAdminOrAbove])
def loyalty_cards_view(request):
    """GET /api/admin/loyalty/ — reglas, resumen y clientes con tarjeta (llenas primero)."""
    cfg = LoyaltySettings.load()
    today = timezone.localdate()
    cards = [c for c in build_cards(cfg, today).values() if c['active'] or c['redemptions']]

    summary = {
        'clients': sum(1 for c in cards if c['active']),
        'ready': sum(1 for c in cards if c['complete']),
        'expiring': sum(1 for c in cards if _expires_soon(c, today)),
        'redeemed': sum(len(c['redemptions']) for c in cards),
    }

    search = (request.query_params.get('search') or '').strip().lower()
    if search:
        digits = phone_key(search)
        cards = [c for c in cards if search in c['name'].lower() or (digits and digits in c['phone'])]

    cards.sort(key=lambda c: (not c['complete'], -c['active'], c['next_expiry'] or '9999'))
    rows = [{k: c[k] for k in CARD_ROW_FIELDS} for c in cards[:300]]
    for row, card in zip(rows, cards):
        row['expires_soon'] = _expires_soon(card, today)
    return Response({'settings': settings_dict(cfg), 'summary': summary, 'cards': rows})


@api_view(['GET'])
@permission_classes([IsAdminOrAbove])
def loyalty_card_view(request, phone):
    """GET /api/admin/loyalty/<celular>/ — la tarjeta de un cliente con su historial."""
    cfg = LoyaltySettings.load()
    card = build_card(phone, cfg)
    if card is None:
        return Response({'error': 'Ese cliente todavía no tiene sellos.'}, status=status.HTTP_404_NOT_FOUND)
    card['settings'] = settings_dict(cfg)
    return Response(card)


@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def loyalty_redeem_view(request, phone):
    """POST /api/admin/loyalty/<celular>/redeem/ — canjea una tarjeta llena."""
    key = phone_key(phone)
    LoyaltySettings.load()  # asegura que la fila exista antes de bloquearla
    with transaction.atomic():
        # Bloquea las reglas: dos canjes a la vez no pueden gastar los mismos sellos.
        cfg = LoyaltySettings.objects.select_for_update().get(pk=1)
        card = build_card(key, cfg)
        if not card or not card['complete']:
            have = card['active'] if card else 0
            return Response(
                {'error': f'La tarjeta tiene {have} de {cfg.stamps_required} sellos: todavía no se puede canjear.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        service = cfg.reward_service
        service_id = request.data.get('reward_service_id')
        if service_id:
            service = Service.objects.filter(pk=service_id).first()
            if service is None:
                return Response({'error': 'Ese servicio no existe.'}, status=status.HTTP_400_BAD_REQUEST)
        red = LoyaltyRedemption.objects.create(
            phone=key, client_name=card['name'], stamps_used=cfg.stamps_required,
            reward_service=service, notes=str(request.data.get('notes') or '')[:200],
            redeemed_by=request.user,
        )
    card = build_card(key, cfg)
    card['settings'] = settings_dict(cfg)
    return Response({'id': red.id, 'card': card}, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsSuperAdmin])
def loyalty_redemption_delete_view(request, pk):
    """DELETE /api/admin/loyalty/redemptions/<id>/ — deshace un canje hecho por error."""
    deleted, _ = LoyaltyRedemption.objects.filter(pk=pk).delete()
    if not deleted:
        return Response({'error': 'Ese canje no existe.'}, status=status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET', 'PUT'])
@permission_classes([IsAdminOrAbove])
def loyalty_settings_view(request):
    """GET/PUT /api/admin/loyalty/settings/ — reglas de la tarjeta (cambiarlas: socios)."""
    cfg = LoyaltySettings.load()
    if request.method == 'GET':
        services = Service.objects.order_by('price', 'name').values('id', 'name', 'price')
        return Response({
            'settings': settings_dict(cfg),
            'services': [{'id': s['id'], 'name': s['name'], 'price': int(s['price'] or 0)} for s in services],
        })

    if not request.user.profile.can_manage_promotions:
        return Response({'error': 'Solo los socios pueden cambiar las reglas de la tarjeta.'},
                        status=status.HTTP_403_FORBIDDEN)
    data, errors = request.data, {}

    def as_int(name, lo, hi, label):
        try:
            value = int(Decimal(str(data.get(name, getattr(cfg, name)))))
        except (InvalidOperation, ValueError, TypeError):
            errors[name] = f'{label}: escribe un número.'
            return None
        if not lo <= value <= hi:
            errors[name] = f'{label}: debe estar entre {lo:,} y {hi:,}.'.replace(',', '.')
            return None
        return value

    stamps = as_int('stamps_required', 1, 50, 'Sellos para el premio')
    min_price = as_int('min_service_price', 0, 10_000_000, 'Precio mínimo')
    months = as_int('expiry_months', 0, 60, 'Meses de vigencia')
    service = cfg.reward_service
    if 'reward_service_id' in data:
        sid = data.get('reward_service_id')
        service = Service.objects.filter(pk=sid).first() if sid else None
        if sid and service is None:
            errors['reward_service_id'] = 'Ese servicio no existe.'
    if errors:
        return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

    cfg.stamps_required, cfg.min_service_price, cfg.expiry_months = stamps, min_price, months
    cfg.reward_service = service
    cfg.reward_note = str(data.get('reward_note', cfg.reward_note) or '')[:200]
    cfg.updated_by = request.user
    cfg.save()
    return Response({'settings': settings_dict(cfg)})
