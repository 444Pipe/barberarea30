"""Festivos colombianos — cálculo determinista, sin dependencias externas.

La barbería atiende los festivos con el mismo horario del domingo (2 a 7 p.m.),
así que la disponibilidad necesita saber si una fecha es festivo. Se calcula en
código (no en base de datos) para que funcione con cualquier año sin que nadie
tenga que cargar fechas a mano cada enero.

Reglas:
  - Festivos de fecha fija: no se mueven.
  - Ley Emiliani (Ley 51 de 1983): se trasladan al lunes siguiente.
  - Festivos religiosos derivados de la Pascua: Jueves y Viernes Santo caen en
    su día real; Ascensión, Corpus Christi y Sagrado Corazón ya se cuentan en
    el lunes que les corresponde.

`BlockedDate` sigue teniendo prioridad: si los socios cargan una fecha a mano,
esa manda sobre lo que diga este módulo.
"""

from datetime import date, timedelta
from functools import lru_cache


# Festivos de fecha fija (mes, día) — NO se trasladan.
_FIXED = (
    (1, 1),    # Año Nuevo
    (5, 1),    # Día del Trabajo
    (7, 20),   # Grito de Independencia
    (8, 7),    # Batalla de Boyacá
    (12, 8),   # Inmaculada Concepción
    (12, 25),  # Navidad
)

# Festivos que se trasladan al lunes siguiente (Ley Emiliani).
_EMILIANI = (
    (1, 6),    # Reyes Magos
    (3, 19),   # San José
    (6, 29),   # San Pedro y San Pablo
    (8, 15),   # Asunción de la Virgen
    (10, 12),  # Día de la Raza
    (11, 1),   # Todos los Santos
    (11, 11),  # Independencia de Cartagena
)

# Días de desplazamiento respecto al Domingo de Pascua.
# Jueves/Viernes Santo caen en su día real; los otros tres ya están corridos al
# lunes por la Ley Emiliani.
_EASTER_OFFSETS = (
    -3,   # Jueves Santo
    -2,   # Viernes Santo
    43,   # Ascensión del Señor
    64,   # Corpus Christi
    71,   # Sagrado Corazón de Jesús
)


def easter_sunday(year):
    """Domingo de Pascua del año dado (algoritmo gregoriano anónimo)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _next_monday(d):
    """Traslada `d` al lunes siguiente. Si ya es lunes, se queda igual."""
    return d + timedelta(days=(7 - d.weekday()) % 7)


@lru_cache(maxsize=32)
def colombian_holidays(year):
    """Conjunto de fechas festivas en Colombia para el año dado."""
    days = {date(year, month, day) for month, day in _FIXED}
    days.update(_next_monday(date(year, month, day)) for month, day in _EMILIANI)

    easter = easter_sunday(year)
    days.update(easter + timedelta(days=offset) for offset in _EASTER_OFFSETS)

    # Un festivo corrido al lunes puede caer en el año siguiente (ej. 28-dic
    # nunca, pero la Ascensión sí puede desbordar en años raros). Se recorta.
    return frozenset(d for d in days if d.year == year)


def is_holiday(target_date):
    """True si `target_date` es festivo en Colombia."""
    if target_date is None:
        return False
    return target_date in colombian_holidays(target_date.year)


def holiday_name(target_date):
    """Nombre del festivo, o cadena vacía si la fecha no lo es.

    Solo para mostrar en el panel; el cálculo de disponibilidad usa
    `is_holiday`.
    """
    if not is_holiday(target_date):
        return ''

    year = target_date.year
    names = {
        date(year, 1, 1): 'Año Nuevo',
        date(year, 5, 1): 'Día del Trabajo',
        date(year, 7, 20): 'Grito de Independencia',
        date(year, 8, 7): 'Batalla de Boyacá',
        date(year, 12, 8): 'Inmaculada Concepción',
        date(year, 12, 25): 'Navidad',
    }
    emiliani_names = (
        ((1, 6), 'Reyes Magos'),
        ((3, 19), 'San José'),
        ((6, 29), 'San Pedro y San Pablo'),
        ((8, 15), 'Asunción de la Virgen'),
        ((10, 12), 'Día de la Raza'),
        ((11, 1), 'Todos los Santos'),
        ((11, 11), 'Independencia de Cartagena'),
    )
    for (month, day), name in emiliani_names:
        names.setdefault(_next_monday(date(year, month, day)), name)

    easter = easter_sunday(year)
    easter_names = (
        (-3, 'Jueves Santo'),
        (-2, 'Viernes Santo'),
        (43, 'Ascensión del Señor'),
        (64, 'Corpus Christi'),
        (71, 'Sagrado Corazón de Jesús'),
    )
    for offset, name in easter_names:
        names.setdefault(easter + timedelta(days=offset), name)

    return names.get(target_date, 'Festivo')
