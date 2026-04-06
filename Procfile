web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2
release: DJANGO_SETTINGS_MODULE=config.settings.production python manage.py migrate --noinput && DJANGO_SETTINGS_MODULE=config.settings.production python manage.py collectstatic --noinput && DJANGO_SETTINGS_MODULE=config.settings.production python seed.py
