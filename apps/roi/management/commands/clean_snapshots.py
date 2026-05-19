"""
clean_snapshots — Borrado selectivo de MonthlyROISnapshot por periodo.

Pensado para limpiar registros corruptos (ej: netos negativos por doble conteo
de Frank antes de la nueva lógica de cierre).

Uso típico:
    python manage.py clean_snapshots --periods 2/2026 3/2026 4/2026
    python manage.py clean_snapshots --periods 4/2026 --force-locked
    python manage.py clean_snapshots --all-unlocked
"""
from django.core.management.base import BaseCommand, CommandError

from apps.roi.services import delete_snapshots
from apps.roi.models import MonthlyROISnapshot


def _parse_period(raw: str):
    """Convierte 'M/YYYY' o 'YYYY-M' en una tupla (year, month)."""
    raw = raw.strip()
    if '/' in raw:
        m, y = raw.split('/')
    elif '-' in raw:
        y, m = raw.split('-')
    else:
        raise CommandError(
            f"Periodo inválido: '{raw}'. Usa formato M/YYYY (ej: 4/2026) o YYYY-M."
        )
    try:
        year = int(y)
        month = int(m)
    except ValueError:
        raise CommandError(f"Periodo inválido: '{raw}'. Año y mes deben ser enteros.")
    if not (1 <= month <= 12):
        raise CommandError(f"Mes fuera de rango en '{raw}': {month}. Debe ser 1-12.")
    if not (2020 <= year <= 2100):
        raise CommandError(f"Año fuera de rango en '{raw}': {year}.")
    return year, month


class Command(BaseCommand):
    help = (
        'Borra MonthlyROISnapshots por periodo. Por defecto NO toca los bloqueados. '
        'Ejemplo: python manage.py clean_snapshots --periods 2/2026 3/2026 4/2026'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--periods',
            nargs='+',
            metavar='M/YYYY',
            help='Lista de periodos a borrar (ej: 2/2026 3/2026 4/2026).',
        )
        parser.add_argument(
            '--all-unlocked',
            action='store_true',
            help='Borra TODOS los snapshots no bloqueados (equivalente a reset_roi pero respetando locks).',
        )
        parser.add_argument(
            '--force-locked',
            action='store_true',
            help='Permite borrar incluso los snapshots con is_locked=True. ¡Úsalo con cuidado!',
        )

    def handle(self, *args, **opts):
        if not opts['periods'] and not opts['all_unlocked']:
            raise CommandError(
                'Debes indicar --periods M/YYYY ... o --all-unlocked. '
                'Ejemplo: python manage.py clean_snapshots --periods 2/2026 3/2026 4/2026'
            )

        if opts['all_unlocked']:
            # Construye la lista a partir de todos los snapshots existentes (no bloqueados).
            existing = MonthlyROISnapshot.objects.filter(is_locked=False).values_list('year', 'month')
            periods = list(existing)
            self.stdout.write(self.style.WARNING(
                f'Modo --all-unlocked: se detectaron {len(periods)} snapshots no bloqueados.'
            ))
        else:
            periods = [_parse_period(p) for p in opts['periods']]

        if not periods:
            self.stdout.write(self.style.SUCCESS('No hay snapshots que borrar. Nada que hacer.'))
            return

        result = delete_snapshots(periods, force_locked=opts['force_locked'])

        self.stdout.write(self.style.SUCCESS(
            f"[OK] Eliminados {result['deleted']} snapshots."
        ))
        if result['skipped_locked']:
            locked_str = ', '.join(f'{m}/{y}' for (y, m) in result['skipped_locked'])
            self.stdout.write(self.style.WARNING(
                f"[WARN] Saltados por estar bloqueados: {locked_str}. "
                f"Usa --force-locked si realmente quieres borrarlos."
            ))
