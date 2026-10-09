"""¿De qué barbero son los datos que pide este usuario?

Lo comparten la agenda y las estadísticas del barbero: el barbero ve lo suyo;
admin, operativo y superadmin pueden pedir el de cualquiera con ?barber=ID y
reciben la lista para elegir.
"""
from .models import Barber


class BarberAccessError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.message = message
        self.status = status


def resolve_target_barber(request):
    """Devuelve (barber, is_admin, barbers_para_elegir) o lanza BarberAccessError."""
    profile = getattr(request.user, 'profile', None)
    is_admin = bool(profile and profile.is_admin)
    own_barber = getattr(request.user, 'barber_profile', None)

    barber = own_barber
    requested = request.query_params.get('barber')
    if requested and is_admin:
        barber = Barber.objects.filter(pk=requested).first()
    elif requested and own_barber is not None and str(own_barber.pk) != str(requested):
        raise BarberAccessError('Solo puedes ver tus propios datos.', 403)

    barbers = []
    if is_admin:
        barbers = [
            {'id': b.id, 'name': b.display_name, 'color': b.color_tag}
            for b in Barber.objects.order_by('display_order', 'id')
        ]
    if barber is None:
        if is_admin and barbers:
            barber = Barber.objects.get(pk=barbers[0]['id'])
        else:
            raise BarberAccessError('Tu usuario no tiene un perfil de barbero asociado.', 400)
    return barber, is_admin, barbers
