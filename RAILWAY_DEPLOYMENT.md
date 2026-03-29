# 🚀 Despliegue en Railway - Área 30 Barber Club (Django)

Esta guía explica cómo desplegar el proyecto Django **Área 30 Barber Club** en Railway.

## 1. Requisitos previos

- Cuenta en [Railway](https://railway.app/)
- Repositorio en GitHub: `https://github.com/444Pipe/barberarea30.git`
- Rama de producción (ej. `main` o `master`)

El proyecto ya incluye:
- `Procfile`: Comando para `gunicorn` y comandos de `release` (migraciones y collectstatic).
- `requirements.txt`: Dependencias de Django y producción.
- `runtime.txt`: Versión de Python específica.
- `config/settings/production.py`: Configuración optimizada para Railway.

## 2. Crear el proyecto en Railway

1. Inicia sesión en Railway.
2. Haz clic en **New Project**.
3. Selecciona **Deploy from GitHub Repo**.
4. Conecta tu cuenta y elige el repositorio `barberarea30`.
5. Railway detectará automáticamente el `Procfile`.

## 3. Variables de entorno necesarias

En la sección **Variables** de Railway, configura:

- `DJANGO_SETTINGS_MODULE` → `config.settings.production`
- `SECRET_KEY` → Una cadena segura y aleatoria.
- `ALLOWED_HOSTS` → `tu-app.up.railway.app,localhost`
- `DEBUG` → `False` (por defecto en production.py)
- `DATABASE_URL` → Railway lo inyecta automáticamente si añades una base de datos PostgreSQL al proyecto.

## 4. Base de Datos (PostgreSQL)

Se recomienda usar PostgreSQL en Railway:
1. Haz clic en **+ Add Service**.
2. Selecciona **Database** → **Add PostgreSQL**.
3. Railway conectará automáticamente la base de datos a tu servicio Django mediante la variable `DATABASE_URL`.

## 5. Archivos Estáticos

El proyecto usa `WhiteNoise` para servir archivos estáticos automáticamente. Durante el despliegue, Railway ejecutará `python manage.py collectstatic` gracias al `Procfile`.

## 6. Comandos útiles

- El `Procfile` incluye un paso de `release` que ejecuta migraciones automáticamente:
  `release: python manage.py migrate --noinput && python manage.py collectstatic --noinput`

---
Configuración lista para producción.
sistencia) y las variables de entorno necesarias para producción.
