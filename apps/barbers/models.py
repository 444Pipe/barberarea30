from django.db import models
from django.contrib.auth.models import User

from apps.users.models import Barbershop
from apps.services.models import Service

# Use RawMediaCloudinaryStorage for video uploads to bypass Pillow image validation.
# Wrapped in try/except so local dev (no cloudinary) falls back gracefully.
try:
    from cloudinary_storage.storage import RawMediaCloudinaryStorage as _RawStorage
    _video_storage = _RawStorage()
except Exception:
    from django.core.files.storage import default_storage
    _video_storage = default_storage


# Horario dominical — también se aplica a los festivos colombianos.
# `end` es la hora de cierre y `last_start` la hora de la ÚLTIMA cita agendable.
# Se atiende de 2 a 7, pero la última cita queda a las 6:30 p.m.: un servicio de
# una hora que empezara a las 7 terminaría a las 8, muy pasado el cierre
# (petición del dueño, 26-jul-2026).
SUNDAY_SCHEDULE = {'start': '14:00', 'end': '19:00', 'last_start': '18:30'}


def _parse_hhmm(value):
    """'HH:MM' → datetime.time. Devuelve None si viene vacío."""
    if not value:
        return None
    from datetime import datetime as _dt
    return _dt.strptime(value, '%H:%M').time()


class Barber(models.Model):
    """Perfil de barbero con horario y especialidades."""
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='barber_profile'
    )
    barbershop = models.ForeignKey(
        Barbershop, on_delete=models.CASCADE, related_name='barbers'
    )
    display_name = models.CharField(max_length=100)
    specialties = models.ManyToManyField(Service, blank=True, related_name='specialist_barbers')
    avatar = models.ImageField(upload_to='barbers/', null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    bio = models.TextField(blank=True)
    is_available = models.BooleanField(default=True)
    # Weekly schedule: {"monday": {"start": "09:00", "end": "20:00"}, ...}
    # Use null for days off
    schedule = models.JSONField(default=dict, blank=True)
    color_tag = models.CharField(
        max_length=7, default='#D4AF37',
        help_text='Color hexadecimal para el calendario'
    )
    total_cuts = models.IntegerField(default=0)
    rating = models.DecimalField(max_digits=2, decimal_places=1, default=5.0)
    display_order = models.IntegerField(default=0, help_text='Orden de aparición en la web pública')
    commission_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=40.0,
        help_text='Porcentaje de comisión estándar (0-100)'
    )
    # Punto de partida del saldo/ledger: si está fijado, solo se cuentan las
    # comisiones, vales y pagos POSTERIORES a esta fecha. Sirve para "reiniciar"
    # el acumulado de un barbero (ej. Frank) dejando su historial intacto en BD.
    ledger_reset_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Barbero'
        verbose_name_plural = 'Barberos'

    def __str__(self):
        return self.display_name

    def get_default_schedule(self):
        """Devuelve horario por defecto (L-V 10–20, Sáb 09–21, Dom 14–19)."""
        return {
            'monday': {'start': '10:00', 'end': '20:00'},
            'tuesday': {'start': '10:00', 'end': '20:00'},
            'wednesday': {'start': '10:00', 'end': '20:00'},
            'thursday': {'start': '10:00', 'end': '20:00'},
            'friday': {'start': '10:00', 'end': '20:00'},
            'saturday': {'start': '09:00', 'end': '21:00'},
            'sunday': SUNDAY_SCHEDULE.copy(),
        }

    def save(self, *args, **kwargs):
        if not self.schedule:
            self.schedule = self.get_default_schedule()
        super().save(*args, **kwargs)

    def work_hours_for(self, target_date, candidates=None):
        """Horario de trabajo temporal (BarberWorkHours) vigente ese día, o None.

        Si hay varios, gana el más reciente. `candidates` permite pasar una
        lista ya cargada para no consultar la BD día por día.
        """
        if candidates is None:
            candidates = self.work_hours.filter(
                date_from__lte=target_date, date_to__gte=target_date
            )
        matches = [wh for wh in candidates if wh.applies_to(target_date)]
        if not matches:
            return None
        return max(matches, key=lambda wh: (wh.created_at, wh.pk))

    def day_window(self, target_date, work_hours=None):
        """Ventana de atención de ESTE barbero en `target_date`.

        Devuelve un dict con `start`, `end`, `last_start` (`datetime.time`, el
        último puede ser None) y `source`, o None si ese día no se atiende.

        Los festivos colombianos usan la ventana del domingo — decisión de los
        socios: festivo = horario dominical. Un horario de trabajo temporal
        (BarberWorkHours) recorta esa ventana (source='custom'). `BlockedDate`
        NO se resuelve aquí: es un override global que manda sobre todo y vive
        en la capa de disponibilidad.
        """
        window = self._base_day_window(target_date)
        if window is None:
            return None
        custom = self.work_hours_for(target_date, work_hours)
        if custom is None:
            return window
        start = max(window['start'], custom.start_time)
        end = min(window['end'], custom.end_time)
        if start >= end:
            return None
        # La "última cita" del domingo/festivo solo sigue valiendo si el horario
        # temporal no corta antes del cierre; si corta, el servicio debe
        # terminar dentro del horario.
        last_start = window['last_start'] if custom.end_time >= window['end'] else None
        if last_start is not None and last_start < start:
            last_start = None
        return {
            'start': start,
            'end': end,
            'last_start': last_start,
            'source': 'custom',
            'base_source': window['source'],
            'reason': custom.reason,
        }

    def _base_day_window(self, target_date):
        """Ventana según el horario semanal (con festivo → horario dominical)."""
        from apps.bookings.holidays import is_holiday

        day_names = ['monday', 'tuesday', 'wednesday', 'thursday',
                     'friday', 'saturday', 'sunday']
        source = 'schedule'
        day_key = day_names[target_date.weekday()]
        if day_key != 'sunday' and is_holiday(target_date):
            day_key = 'sunday'
            source = 'holiday'

        day_schedule = (self.schedule or {}).get(day_key)
        if not day_schedule:
            return None
        try:
            window = {
                'start': _parse_hhmm(day_schedule['start']),
                'end': _parse_hhmm(day_schedule['end']),
                'last_start': _parse_hhmm(day_schedule.get('last_start')),
                'source': source,
            }
        except (KeyError, TypeError, ValueError):
            return None
        if window['start'] is None or window['end'] is None:
            return None
        return window

    def window_violation(self, target_date, start_time, end_time):
        """Mensaje de error si una cita cae fuera del horario, o None si cabe.

        La disponibilidad del front ya oculta estas horas, pero un POST directo
        (o una página cacheada con el horario viejo) las colaba: esta es la
        validación del lado del servidor.

        `end_time` es la hora a la que terminaría el servicio.
        """
        window = self.day_window(target_date)
        if not window:
            return (
                f'{self.display_name} no atiende el {target_date.strftime("%d/%m/%Y")}. '
                f'Por favor elige otra fecha.'
            )

        if window['source'] == 'custom':
            etiqueta = f'Ese día {self.display_name} trabaja solo de'
            limite = window['last_start'] or window['end']
            franja = f'{window["start"].strftime("%I:%M %p")} a {limite.strftime("%I:%M %p")}'
            if start_time < window['start'] or (
                window['last_start'] and start_time > window['last_start']
            ) or (not window['last_start'] and (end_time > window['end'] or end_time <= start_time)):
                return (
                    f'{etiqueta} {franja}. '
                    f'El servicio tiene que caber dentro de ese horario.'
                )
            return None

        etiqueta = 'En los festivos' if window['source'] == 'holiday' else 'Ese día'
        limite = window['last_start'] or window['end']
        franja = (
            f'{window["start"].strftime("%I:%M %p")} a '
            f'{limite.strftime("%I:%M %p")}'
        )

        if start_time < window['start']:
            return f'{etiqueta} se atiende de {franja}. La hora que elegiste es muy temprano.'

        if window['last_start']:
            if start_time > window['last_start']:
                return f'{etiqueta} la última cita es a las {window["last_start"].strftime("%I:%M %p")}.'
        elif end_time > window['end'] or end_time <= start_time:
            return (
                f'{etiqueta} se atiende de {franja}. '
                f'El servicio no alcanza a terminar dentro de ese horario.'
            )
        return None

    @property
    def is_frank(self):
        """Frank tiene comportamiento especial (slots de 2h en cualquier servicio)."""
        return 'frank' in (self.display_name or '').lower()

    def effective_duration_minutes(self, service):
        """Duración real de una reserva para ESTE barbero ofreciendo `service`.

        Frank usa siempre 2h por servicio (decisión de negocio). El resto de
        barberos toma la duración del servicio (default 60).
        """
        if self.is_frank:
            return 120
        if service is None:
            return 60
        return service.duration_minutes or 60

    def occupied_minutes(self, stored_duration_minutes):
        """Minutos que realmente ocupa una cita de ESTE barbero al detectar
        solapamientos.

        Frank ocupa 2h aunque la reserva se haya guardado con otra duración
        (datos antiguos o creados por flujos que no aplicaron la regla). Esto
        hace que la detección de cruces sea correcta sin depender del valor
        guardado en `duration_minutes`.
        """
        if self.is_frank:
            return 120
        return stored_duration_minutes or 60


class BarberWorkHours(models.Model):
    """Horario de trabajo temporal: lo contrario de un bloqueo.

    En vez de decir cuándo NO trabaja, dice cuándo SÍ: entre `date_from` y
    `date_to` (inclusive), en los días de la semana elegidos, el barbero solo
    recibe citas de `start_time` a `end_time`. Se cruza con su horario semanal
    (nunca lo amplía) y se aplica en `Barber.day_window`, así que la web, la
    validación de reservas y la agenda lo respetan sin código aparte.
    Nace del caso de Frank (oct-2026): un bloqueo de 1 a 9 p.m. se leía como
    "bloqueado todo el día" y las mañanas quedaban abiertas sin que nadie lo notara.
    """
    barber = models.ForeignKey(
        Barber, on_delete=models.CASCADE, related_name='work_hours'
    )
    date_from = models.DateField()
    date_to = models.DateField()
    # 0=lunes … 6=domingo. Vacío = todos los días.
    weekdays = models.JSONField(default=list, blank=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Horario de trabajo'
        verbose_name_plural = 'Horarios de trabajo'
        ordering = ['date_from', 'start_time']

    def __str__(self):
        return (f'{self.barber.display_name} – {self.date_from}→{self.date_to} '
                f'{self.start_time}–{self.end_time}')

    def applies_to(self, target_date):
        if not (self.date_from <= target_date <= self.date_to):
            return False
        return not self.weekdays or target_date.weekday() in self.weekdays


class BarberUnavailability(models.Model):
    """Bloqueo temporal de un barbero en una fecha y rango de hora."""
    barber = models.ForeignKey(
        Barber, on_delete=models.CASCADE, related_name='unavailabilities'
    )
    date = models.DateField(help_text='Fecha del bloqueo')
    start_time = models.TimeField(help_text='Hora de inicio del bloqueo')
    end_time = models.TimeField(help_text='Hora de fin del bloqueo')
    reason = models.CharField(
        max_length=255, blank=True,
        help_text='Motivo opcional (emergencia, cita médica, etc.)'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Inactividad Temporal'
        verbose_name_plural = 'Inactividades Temporales'
        ordering = ['date', 'start_time']

    def __str__(self):
        return f'{self.barber.display_name} – {self.date} {self.start_time}–{self.end_time}'


class GalleryImage(models.Model):
    """Imagen de galería — trabajos realizados."""
    image = models.ImageField(upload_to='gallery/')
    title = models.CharField(max_length=150, blank=True)
    barber = models.ForeignKey(
        Barber, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='gallery_images'
    )
    display_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Imagen de Galería'
        verbose_name_plural = 'Imágenes de Galería'
        ordering = ['-created_at']

    def __str__(self):
        return self.title or f'Imagen #{self.pk}'


class Reel(models.Model):
    """Video estilo reel — trabajos en video para la página pública."""
    video = models.FileField(
        upload_to='reels/',
        storage=_video_storage,  # RawMediaCloudinaryStorage in prod, default locally
        help_text='Video MP4 vertical (9:16 recomendado)'
    )
    thumbnail = models.ImageField(upload_to='reels/thumbs/', null=True, blank=True,
        help_text='Miniatura opcional. Si no se sube se usa el primer frame del video.')
    title = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    barber = models.ForeignKey(
        Barber, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reels'
    )
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Reel'
        verbose_name_plural = 'Reels'
        ordering = ['display_order', '-created_at']

    def __str__(self):
        return self.title or f'Reel #{self.pk}'
