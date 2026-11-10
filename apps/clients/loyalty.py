"""Tarjeta de sellos (prueba, nov-2026). Por ahora solo se ve en el panel.

Regla del dueño: un sello cuenta cuando el servicio se COBRÓ y la venta quedó
APROBADA en caja. Reservar no suma; tampoco una cita cancelada, una ausencia,
una venta pendiente o rechazada.

Los sellos no se guardan en ninguna tabla: se calculan cada vez desde las
ventas aprobadas, así una venta que se rechaza después deja de contar sola y
un cambio de reglas aplica de inmediato. Lo único que se guarda es el canje
(`LoyaltyRedemption`), que gasta los sellos vigentes más antiguos.

Suma sello una venta:
  - aprobada, ligada a una cita (de ahí sale el celular del cliente);
  - con precio de lista (`base_price`) desde `min_service_price`;
  - que no fue gratis (`final_price > 0`): el servicio de premio no suma.
Cada sello vence `expiry_months` meses después del día del servicio.
"""
import calendar
import re
from collections import defaultdict
from datetime import date

from django.utils import timezone

from apps.cashflow.models import Sale

from .models import LoyaltyRedemption, LoyaltySettings


def phone_key(raw):
    """Celular del cliente como clave: solo dígitos y sin el 57 del país.
    '311 265 1032', '+57 311-265-1032' y '3112651032' son la misma tarjeta."""
    digits = re.sub(r'\D', '', raw or '')
    if len(digits) == 12 and digits.startswith('57'):
        digits = digits[2:]
    return digits


def add_months(day, months):
    """Misma fecha `months` meses después (31-ago + 6 → 28/29-feb)."""
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _stamp_rows(cfg):
    return (
        Sale.objects
        .filter(
            approval_status=Sale.STATUS_APPROVED,
            booking__isnull=False,
            base_price__gte=cfg.min_service_price,
            final_price__gt=0,
        )
        .exclude(booking__status='cancelled')
        .values(
            'id', 'base_price', 'booking__client_phone', 'booking__client_name',
            'booking__date', 'service__name', 'booking__service__name',
            'barber__display_name',
        )
        .order_by('booking__date', 'booking__time', 'id')
    )


def _build_card(key, stamps, redemptions, cfg, today, name):
    # Cada canje gasta, en su día, los sellos vigentes más antiguos.
    for red in redemptions:
        day = timezone.localdate(red.redeemed_at)
        usable = [
            s for s in stamps
            if s['state'] == 'activo' and s['date'] <= day
            and (s['expires'] is None or s['expires'] > day)
        ]
        for s in usable[:red.stamps_used]:
            s['state'] = 'usado'
    for s in stamps:
        if s['state'] == 'activo' and s['expires'] is not None and s['expires'] <= today:
            s['state'] = 'vencido'

    active = [s for s in stamps if s['state'] == 'activo']
    required = cfg.stamps_required
    if not name and redemptions:
        name = redemptions[-1].client_name
    return {
        'phone': key,
        'name': name or 'Cliente',
        'active': len(active),
        'required': required,
        'complete': len(active) >= required,
        'missing': max(0, required - len(active)),
        # El sello más antiguo es el primero en vencer.
        'next_expiry': active[0]['expires'].isoformat() if active and active[0]['expires'] else None,
        'last_visit': stamps[-1]['date'].isoformat() if stamps else None,
        'stamps': [
            {
                'sale_id': s['sale_id'],
                'date': s['date'].isoformat(),
                'service': s['service'],
                'barber': s['barber'],
                'price': s['price'],
                'expires': s['expires'].isoformat() if s['expires'] else None,
                'state': s['state'],
            }
            for s in reversed(stamps)
        ],
        'redemptions': [
            {
                'id': r.id,
                'date': timezone.localtime(r.redeemed_at).strftime('%Y-%m-%d %H:%M'),
                'stamps_used': r.stamps_used,
                'service': r.reward_service.name if r.reward_service else '',
                'notes': r.notes,
                'by': (r.redeemed_by.get_full_name() or r.redeemed_by.username) if r.redeemed_by else '',
            }
            for r in reversed(redemptions)
        ],
    }


def build_cards(cfg=None, today=None, only_key=None):
    """Tarjetas de todos los clientes (o de uno, con `only_key`) → {clave: tarjeta}."""
    cfg = cfg or LoyaltySettings.load()
    today = today or timezone.localdate()

    stamps_by, names = defaultdict(list), {}
    for r in _stamp_rows(cfg):
        key = phone_key(r['booking__client_phone'])
        if not key or (only_key and key != only_key):
            continue
        day = r['booking__date']
        stamps_by[key].append({
            'sale_id': r['id'],
            'date': day,
            'expires': add_months(day, cfg.expiry_months) if cfg.expiry_months else None,
            'service': r['service__name'] or r['booking__service__name'] or 'Servicio',
            'barber': r['barber__display_name'] or '',
            'price': int(r['base_price']),
            'state': 'activo',
        })
        names[key] = r['booking__client_name']  # queda el nombre de la cita más reciente

    redemptions_by = defaultdict(list)
    reds = LoyaltyRedemption.objects.select_related('reward_service', 'redeemed_by').order_by('redeemed_at', 'id')
    if only_key:
        reds = reds.filter(phone=only_key)
    for red in reds:
        redemptions_by[red.phone].append(red)

    return {
        key: _build_card(key, stamps_by.get(key, []), redemptions_by.get(key, []), cfg, today, names.get(key))
        for key in set(stamps_by) | set(redemptions_by)
    }


def build_card(raw_phone, cfg=None, today=None):
    """Tarjeta de un cliente; None si ese celular no tiene sellos ni canjes."""
    key = phone_key(raw_phone)
    if not key:
        return None
    return build_cards(cfg, today, only_key=key).get(key)


def settings_dict(cfg):
    return {
        'stamps_required': cfg.stamps_required,
        'min_service_price': int(cfg.min_service_price),
        'expiry_months': cfg.expiry_months,
        'reward_service_id': cfg.reward_service_id,
        'reward_service': cfg.reward_service.name if cfg.reward_service else '',
        'reward_note': cfg.reward_note,
        'updated_at': timezone.localtime(cfg.updated_at).strftime('%Y-%m-%d %H:%M') if cfg.updated_at else '',
        'updated_by': (cfg.updated_by.get_full_name() or cfg.updated_by.username) if cfg.updated_by else '',
    }
