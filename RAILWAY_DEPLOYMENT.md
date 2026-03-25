# 🚀 Despliegue en Railway - Área 30 Barber Club

Esta guía explica cómo desplegar este proyecto Flask en Railway.

## 1. Requisitos previos

- Cuenta en [Railway](https://railway.app/)
- Repositorio en GitHub con este proyecto (por ejemplo `JuanEdu1/BARBER-CLUB-30`)
- Rama con los cambios listos para producción (por ejemplo `felipe`)

El proyecto ya incluye:
- `Procfile` con el comando para gunicorn
- `requirements.txt` con las dependencias mínimas (`flask`, `gunicorn`)

## 2. Crear el proyecto en Railway

1. Inicia sesión en Railway.
2. Haz clic en **New Project**.
3. Selecciona **Deploy from GitHub Repo**.
4. Conecta tu cuenta de GitHub (si no lo has hecho antes).
5. Elige el repositorio (por ejemplo `JuanEdu1/BARBER-CLUB-30`).
6. Selecciona la rama que quieras desplegar (por ejemplo `felipe`).

Railway detectará automáticamente que es un proyecto Python y usará:

- `requirements.txt` para instalar dependencias.
- `Procfile` para ejecutar el servicio web:
  - `web: gunicorn app:app --bind 0.0.0.0:$PORT --workers 2`

## 3. Variables de entorno necesarias

En la sección **Variables** de tu servicio en Railway, configura al menos:

- `SECRET_KEY` → Una cadena segura y aleatoria para firmar sesiones.
- `ADMIN_USERNAME` → Usuario para el panel admin (por ejemplo `admin`).
- `ADMIN_PASSWORD` → Contraseña para el panel admin (por ejemplo `admin123`).

Opcionales para correo SMTP (recomendado si quieres que los emails se envíen de verdad):

- `SMTP_HOST` → Host SMTP (por ejemplo `smtp.gmail.com`).
- `SMTP_PORT` → Puerto (por defecto `587`).
- `SMTP_USER` → Usuario/correo SMTP.
- `SMTP_PASSWORD` → Password o app password.
- `SMTP_FROM` → Correo que aparecerá como remitente (si se omite, se usa `SMTP_USER`).

Si estas variables **no** se configuran, la app no fallará: simplemente simulará el envío de correos escribiendo en los logs.

## 4. Base de datos (SQLite) en Railway

La app usa SQLite por defecto. La ruta de la base de datos se controla así:

- Por defecto: archivo `bookings.db` en el mismo directorio que `app.py`.
- Se puede sobrescribir con la variable de entorno `DB_PATH`.

```python
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('DB_PATH', os.path.join(BASE_DIR, 'bookings.db'))
```

Al cargar la app (incluido cuando gunicorn importa `app:app`), se ejecuta `init_db()` para asegurar que la tabla `bookings` exista.

### 4.1. Persistencia de datos

En Railway, el sistema de archivos del contenedor puede ser efímero. Para no perder reservas al re-deployar o reiniciar:

1. En tu servicio de Railway, ve a **Settings → Volumes**.
2. Crea un volumen nuevo (por ejemplo `barber-db`) y móntalo en una ruta, por ejemplo `/data`.
3. En **Variables**, define:
   - `DB_PATH=/data/bookings.db`

Con esto, la base de datos SQLite se guardará en el volumen persistente de Railway.

Si **no** configuras un volumen:
- La app seguirá funcionando.
- Pero la base `bookings.db` se puede resetear al redeploy/restart.

## 5. Despliegue y primera ejecución

1. Una vez configurado todo, Railway hará el **build** automáticamente.
2. Al terminar, verás el servicio corriendo con un dominio similar a:
   - `https://nombre-proyecto.up.railway.app`
3. Abre ese dominio en el navegador.

Rutas principales:

- Página pública: `/`
- Servicios: `/services`
- Galería: `/gallery`
- Reserva: `/booking`
- Login admin: `/admin/login`
- Panel admin (reservas): `/admin`

## 6. Probar el flujo completo en producción

1. En la página `/booking`, crea una reserva de prueba.
2. Verifica que el formulario valide fechas (no permite días pasados) y horas ocupadas.
3. Entra a `/admin/login` con `ADMIN_USERNAME` y `ADMIN_PASSWORD`.
4. Comprueba que la reserva aparece en:
   - Tabla de reservas (`/admin` o `/admin/reservas`).
   - Calendario (`/admin/calendario`).
   - Gráficas (`/admin/graficas`) cuando la marques como completada.

Si configuraste SMTP, revisa el correo del cliente de prueba para confirmar que llegan los emails.

## 7. Logs y depuración

- Desde Railway, entra a tu servicio y abre la sección **Logs**.
- Ahí verás:
  - Errores de la app Flask.
  - Simulaciones de envío de correo si no hay SMTP configurado.
  - Peticiones HTTP manejadas por gunicorn.

En caso de errores 500:
- Revisa logs para ver el traceback.
- Verifica que todas las variables de entorno necesarias estén configuradas.

## 8. Actualizar la app

Cada vez que hagas cambios en el código:

1. Haz **commit** y **push** a la rama que Railway está usando (por ejemplo `felipe`).
2. Railway detectará el nuevo commit y lanzará automáticamente un nuevo deploy.
3. Espera a que el deploy termine y vuelve a probar la app en el dominio público.

---

Con esta configuración, el proyecto queda listo para ejecutarse correctamente en Railway usando gunicorn, SQLite (con opción de persistencia) y las variables de entorno necesarias para producción.
