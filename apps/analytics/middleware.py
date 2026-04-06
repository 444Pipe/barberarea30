from django.http import JsonResponse
import traceback

class CatchAllExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        return JsonResponse({
            'error_from_middleware': True,
            'message': str(exception),
            'type': type(exception).__name__,
            'path': request.path
        }, status=500)
