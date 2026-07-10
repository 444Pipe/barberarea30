import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse, Http404

logger = logging.getLogger(__name__)


class CatchAllExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        # 404 y 403 deben manejarlos las vistas/Django normalmente, no
        # convertirse en un 500 (rompía not-found legítimos del sitio público).
        if isinstance(exception, (Http404, PermissionDenied)):
            return None

        # Registrar el detalle del lado del servidor (Railway captura el log).
        logger.error("Error no capturado en %s", request.path, exc_info=exception)

        payload = {'error_from_middleware': True, 'path': request.path}
        if settings.DEBUG:
            # Solo en desarrollo se expone el detalle de la excepción.
            payload['message'] = str(exception)
            payload['type'] = type(exception).__name__
        else:
            payload['message'] = 'Ocurrió un error interno. Inténtalo de nuevo más tarde.'
        return JsonResponse(payload, status=500)
