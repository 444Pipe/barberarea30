# Auditoría técnica — Área 30 Barber Club

Fecha: 2026-07-09
Alcance: backend (Django 5.1 + DRF), sitio público, panel de administración, API y seguridad.
Método: revisión de código real (solo lectura) de `apps/*`, `config/settings/*`, `templates/*`, `static/*` y `seed.py`. Ningún archivo fue modificado.

> **Nota sobre credenciales:** varios hallazgos citan contraseñas reales versionadas en el repositorio. Este documento las referencia por ubicación (archivo:línea) y **no** las reproduce. Deben rotarse de inmediato — ver [SEC-02](#sec-02).

---

## Resumen ejecutivo

Se detectaron **4 problemas de toma de control / manipulación explotables hoy mismo** que deben atenderse antes que nada:

1. **Precio de reserva manipulable desde el sitio público** — un anónimo reserva un servicio premium por $1.000 (o $0), y ese precio fluye a caja, comisiones y ROI.
2. **Cualquier usuario autenticado (incluido un barbero) puede crear, editar precios y borrar servicios** vía `/api/services/`.
3. **`/init-soporte/` + `seed.py` reimponen superadmins con contraseñas fijas del repo** en cada arranque; cualquier anónimo puede recrear un superadmin con clave pública.
4. **Cancelación/reseña de reservas ajenas por ID secuencial sin autenticación** — un atacante itera IDs y cancela la agenda completa.

Además, dos fallas silenciosas de operación: **los recordatorios de cita nunca se envían en producción** y **la consolidación automática de ROI nunca corre bajo gunicorn** (ambos por guards mal escritos en `apps.py`). En la capa financiera, los mayores riesgos de descuadre son el ciclo *eliminar-recerrar* del cierre diario (duplica el pago de Frank), el doble restock al rechazar ventas re-facturadas y las fechas de egresos guardadas en UTC (corren gastos al mes siguiente en el ROI).

### Conteo por severidad

| Severidad | Backend | Seguridad/API | Sitio público | Panel admin | Total aprox. |
|-----------|:-------:|:-------------:|:-------------:|:-----------:|:------------:|
| Crítico   | 4 | 3 | 2 | 3 | 12 (con solapes) |
| Alto      | 6 | 2 | 5 | 6 | — |
| Medio     | 11 | 5 | 5 | 10 | — |
| Bajo      | 11 | 4 | 4 | 10 | — |

Los solapes están consolidados en las secciones siguientes: cada problema aparece una sola vez con todas sus manifestaciones y ubicaciones.

---

## 1. Seguridad y control de acceso

<a id="sec-01"></a>
### SEC-01 · CRÍTICO · Precio de reserva manipulable desde endpoint público
- **Dónde:** `apps/bookings/views.py:285` (`create_booking_view`, `AllowAny`) + `apps/bookings/serializers.py:13` (`price` en `fields`, no read-only).
- **Riesgo:** `price=data.get('price', service.price)` usa el precio enviado por el cliente sin validarlo. Ese valor fluye a `Sale.base_price` en `process_checkout` (`apps/cashflow/services.py:57`) y de ahí a caja, comisiones y ROI. Cualquiera reserva un Diamond VIP de $115.000 con `price: 1000` (o `0`). El modal Walk-in del panel (`templates/admin/bookings.html:879`) también manda `price` desde un `data-price` del DOM.
- **Corrección:** eliminar `price` del serializer público (o hacerlo read-only) y usar siempre `service.price` en el servidor; aceptar `price` del cliente solo si `request.user` es staff.

<a id="sec-02"></a>
### SEC-02 · CRÍTICO · Superadmins con contraseñas fijas reimpuestas en cada deploy
- **Dónde:** `seed.py:225-242,279` y `apps/users/management/commands/createsoporte.py:9-32`.
- **Riesgo:** `seed.py` corre en **cada boot** (Procfile) y ejecuta `user.set_password(...)` incondicionalmente con contraseñas en texto plano versionadas en git (socios `camilorf`, `juandavid.castro`, más `soporte_tecnico` y `frank`). Si un socio cambia su clave, el siguiente deploy la revierte al valor filtrado. `createsoporte` crea `soporte` con `is_superuser=True` y contraseña fija.
- **Corrección:** mover contraseñas a variables de entorno; asignar contraseña **solo al crear** (`if created:`), nunca en cada boot; rotar de inmediato todas las credenciales expuestas.

<a id="sec-03"></a>
### SEC-03 · CRÍTICO · `/init-soporte/` permite a un anónimo crear/resetear un superadmin
- **Dónde:** `config/urls.py:8-28` + `createsoporte.py`.
- **Riesgo:** endpoint GET sin autenticación ni throttling. Cualquier visitante lo abre y recrea el superadmin `soporte` (contraseña pública en el repo), luego entra a `/admin-panel/` o `/django-admin/` con control total.
- **Corrección:** eliminar el endpoint o protegerlo tras superadmin + token de un solo uso; nunca recrear cuentas con contraseña estática.

<a id="sec-04"></a>
### SEC-04 · CRÍTICO · Cancelar/reseñar reservas ajenas por ID secuencial sin auth
- **Dónde:** `apps/bookings/views.py:320-336` (`cancel`, `AllowAny`) y `:339-374` (`review`).
- **Riesgo:** `POST /api/bookings/<id>/cancel/` recibe el ID autoincremental sin firma; un atacante itera IDs y cancela toda la agenda. El flujo correcto (URL firmada con `Signer` en `client_booking_detail_view`) queda bypaseado. `review` permite inyectar reseñas en reservas ajenas, que se autopublican si son ≥4 estrellas.
- **Corrección:** exigir el `signed_id`/token en ambos endpoints públicos.

<a id="sec-05"></a>
### SEC-05 · CRÍTICO/ALTO · API de servicios y precios escribible por cualquier autenticado
- **Dónde:** `apps/services/views.py:12-35` (`ServiceListView`, `ServiceDetailView` con `IsAuthenticatedOrReadOnly`).
- **Riesgo:** cualquier cuenta con JWT — **incluido un barbero** — puede `POST /api/services/`, `PUT/DELETE /api/services/{id}/` y cambiar precios o borrar servicios. Contradice `can_modify_prices` (solo superadmin). El panel lo esconde en el frontend pero el backend no lo impone. Nota adicional: la página Configuración permite editar precios al rol `admin` (`apps/users/views.py:186`), también contra el modelo de roles.
- **Corrección:** dejar GET público/lectura y mover escritura a `IsSuperAdmin` o `HasProfilePermission(required_permission='can_modify_prices')`.

<a id="sec-06"></a>
### SEC-06 · CRÍTICO · `SECRET_KEY` con default inseguro si falta la variable de entorno
- **Dónde:** `config/settings/base.py:15` y `config/settings/production.py:18`.
- **Riesgo:** `SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')`. Si la variable no está en Railway, producción arranca con la clave pública del repo. Con ella se pueden forjar los `signed_id` de reservas (usados en `client_booking_detail_view`), cookies de sesión y tokens de reseteo.
- **Corrección:** exigir la variable (fallar el arranque con `ImproperlyConfigured` si falta en producción); no proveer un default utilizable.

<a id="sec-07"></a>
### SEC-07 · ALTO · IDOR en galería y reels (barbero edita/borra contenido ajeno)
- **Dónde:** `apps/barbers/views.py:545-586` (`GalleryAdmin*`, `ReelAdmin*` con `IsBarberOrAbove`, sin filtro por dueño). Vistas HTML con `@staff_required` (`apps/users/views.py:196,206`) mientras la API acepta a cualquier barbero.
- **Riesgo:** cualquier barbero autenticado edita/elimina imágenes y reels de otros (`DELETE /api/admin/gallery/{id}/`, `/api/admin/reels/{id}/`) y sube a nombre de cualquiera. El sidebar solo esconde los enlaces.
- **Corrección:** filtrar por `barber=request.user.barber_profile` para roles no-admin, o exigir `IsAdminOrAbove` para escritura/borrado.

<a id="sec-08"></a>
### SEC-08 · ALTO/MEDIO · IDOR en checkout y consumibles (barbero opera reservas ajenas)
- **Dónde:** `apps/cashflow/views.py:20-31` (`checkout_booking_view`) y `apps/inventory/views.py:265-281` (`register_consumables_view`), ambos `IsBarberOrAbove` sin verificar propiedad. Contrasta con `finalizar_cita` (`apps/barbers/views.py:628`), que sí valida al dueño.
- **Riesgo:** un barbero procesa el checkout (genera `Sale`+`Commission`) o descuenta inventario de la reserva de otro, alterando comisiones e inventario ajenos. El botón "COBRAR" aparece en todas las filas. Además puede enviar `frank_materials_cost`/`frank_labor_cost` que reemplazan `base_price`.
- **Corrección:** para rol `barber`, validar `booking.barber == request.user.barber_profile`; restringir los costos manuales a Frank/admins.

<a id="sec-09"></a>
### SEC-09 · ALTO · Panel de aprobaciones roto para el rol `admin` (permiso desalineado)
- **Dónde:** `templates/admin/dashboard.html:109,238` habilitan el panel para `admin` y `apps/users/views.py:98` calcula su contador, pero `pending-approvals`/`approve`/`reject` son `IsOperationalAdminOrAbove` (`apps/cashflow/views.py:577-604`).
- **Riesgo:** el admin recibe 403 que el JS traga en silencio (`.catch(() => {})`, dashboard.html:244): el panel nunca aparece aunque haya ventas pendientes, sin mensaje.
- **Corrección:** alinear permiso y UI (abrir a `IsAdminOrAbove` o quitar `admin` del template y del contador).

<a id="sec-10"></a>
### SEC-10 · ALTO · Middleware convierte 404 en 500 y filtra detalles internos
- **Dónde:** `apps/analytics/middleware.py:11-18` (`CatchAllExceptionMiddleware.process_exception`).
- **Riesgo:** intercepta **toda** excepción — incluido `Http404` de `get_object_or_404`/`Signer` — y devuelve JSON 500 con `str(exception)`, sin importar `DEBUG`. Los 404 legítimos del sitio público responden 500 con mensaje interno (rutas, SQL, columnas), útil para reconocimiento.
- **Corrección:** `if isinstance(exception, Http404): return None` (ídem `PermissionDenied`); limitar a rutas `/api/`; no exponer `str(exception)` en producción, loguearlo del lado servidor.

<a id="sec-11"></a>
### SEC-11 · MEDIO · Endpoints públicos devuelven stack traces completos
- **Dónde:** `apps/bookings/views.py:47-54` (`public_blocked_dates_list`) y `apps/services/views.py:46-48` (`obtener_servicios_nativos`), ambos `AllowAny`, devuelven `traceback.format_exc()` en el JSON de error.
- **Corrección:** no serializar el traceback; loguearlo del lado servidor y devolver mensaje genérico.

<a id="sec-12"></a>
### SEC-12 · MEDIO · Subida de archivos sin validación de tipo/tamaño
- **Dónde:** `apps/barbers/views.py:545-586` (galería/reels), `apps/cashflow/views.py:503-536` (imagen de egreso), `apps/inventory/views.py:38-71,92-121` (imagen de producto).
- **Riesgo:** se aceptan `request.FILES` sin validar content-type, extensión ni tamaño. `Reel.video` usa `RawMediaCloudinaryStorage` que omite la validación de Pillow (por diseño) → se puede subir cualquier binario. Combinado con SEC-07, un barbero sube archivos arbitrarios sin control.
- **Corrección:** `FileExtensionValidator`, validación MIME y límite de tamaño máximo en el serializer.

<a id="sec-13"></a>
### SEC-13 · MEDIO · `daily_close_view` expone bloque `debug` con IDs y totales
- **Dónde:** `apps/cashflow/views.py:190-199` — respuesta incluye `debug` con `ventas_ids`, `egresos_ids`, `inventory_sales_ids` y totales.
- **Corrección:** eliminar el bloque `debug` en producción.

<a id="sec-14"></a>
### SEC-14 · BAJO · Configuración de settings peligrosa por defecto
- `config/settings/development.py:7,20` — `ALLOWED_HOSTS=['*']` y `CORS_ALLOW_ALL_ORIGINS=True` (correcto en dev, peligroso si se selecciona por error).
- `config/settings/production.py:17-19` — `DEBUG` derivado de la ausencia de `DATABASE_URL`; un deploy sin esa variable arranca con `DEBUG=True` + SQLite, exponiendo trazas completas.
- `config/settings/production.py:23` — incluye `localhost,127.0.0.1` en el `ALLOWED_HOSTS` por defecto.
- **Corrección:** exigir `DEBUG=False` explícito en producción; quitar hosts locales del default; documentar que `development` nunca debe cargarse en Railway.

<a id="sec-15"></a>
### SEC-15 · BAJO · Credenciales de barbero generadas devueltas en texto plano
- **Dónde:** `apps/barbers/views.py:216-218` + `serializers.py:100` — `created_password` en la respuesta JSON (queda en historiales/logs/proxies). Falta `autocomplete="off"` en el generador (`templates/admin/barbers.html:82-93`).
- **Corrección:** entregar la clave por canal de un solo uso y forzar cambio en el primer login.

**Verificado y correcto (sin hallazgo):** sin SQL crudo/`.raw()`/`.extra()`/`eval`/`subprocess` con input de usuario; IDOR bien mitigado en `finalizar_cita`, listados/detalle de reservas y `client_booking_detail_view` (URLs firmadas); estadísticas restringen a barberos a sus propios datos; datos personales de clientes solo bajo `IsAdminOrAbove`; CSRF presente en todos los POST/PATCH/DELETE del panel (DRF con `SessionAuthentication`).

---

## 2. Lógica de negocio y finanzas (backend)

<a id="biz-01"></a>
### BIZ-01 · CRÍTICO · Los recordatorios de cita NUNCA se envían en producción
- **Dónde:** `apps/bookings/apps.py:13`.
- **Problema:** el guard `if os.environ.get('RUN_MAIN') != 'true' and os.environ.get('DJANGO_SETTINGS_MODULE'): return` sale de `ready()` antes de crear el `BackgroundScheduler`. En Railway, gunicorn no define `RUN_MAIN` pero `DJANGO_SETTINGS_MODULE` sí está → siempre retorna. Los correos de recordatorio 2h antes de la cita solo funcionan en `runserver` local. Falla silenciosa, sin log.
- **Corrección:** invertir la lógica del guard (saltar solo en el proceso padre del reloader o en comandos de gestión), no cuando la settings-var está definida.

<a id="biz-02"></a>
### BIZ-02 · ALTO · La consolidación automática de ROI tampoco arranca bajo gunicorn
- **Dónde:** `apps/roi/apps.py:13` — `if 'runserver' in sys.argv or 'gunicorn' in sys.argv[0:1]`.
- **Problema:** `sys.argv[0:1]` es una lista con la ruta completa del binario; `in` sobre lista compara igualdad exacta, no substring → siempre `False`. La consolidación del día 1 a las 00:05 nunca corre; los snapshots dependen del botón manual.
- **Corrección:** `'gunicorn' in sys.argv[0]` (substring sobre el string) o el mismo guard corregido de BIZ-01.

<a id="biz-03"></a>
### BIZ-03 · ALTO · Eliminar un cierre diario y recerrar duplica el pago de Frank
- **Dónde:** `apps/cashflow/views.py:310-338` (delete) + `:99-158` (close).
- **Problema:** `delete_daily_close_view` desvincula ventas/egresos pero **no elimina** el `Expense` "Pago Diario: Franko" ni resetea `is_paid` de las comisiones. Al recerrar: las ventas vuelven a pendientes, `frank_commissions` no filtra `is_paid` (línea 124) → se crea un **segundo** egreso de Frank, y `pending_expenses` incluye el viejo + el nuevo → `total_expenses` cuenta el pago dos veces y `net_income` queda subestimado.
- **Corrección:** al eliminar el cierre, borrar el egreso auto-generado y revertir `is_paid`; en el cierre, excluir comisiones ya pagadas.

<a id="biz-04"></a>
### BIZ-04 · ALTO · `seed.py` revierte precios y desactiva servicios en cada deploy
- **Dónde:** `seed.py:119-125` (y `seed_services.py`).
- **Problema:** `update_or_create(slug=..., defaults={**svc})` sobreescribe `price`, `description`, `features` en cada boot; si un superadmin cambia un precio desde el panel (la función estrella de `can_modify_prices`), el siguiente deploy lo revierte. `Service.objects.update(is_active=False)` desactiva servicios creados desde el panel. (Ver también panel: un servicio borrado a mano "resucita" en el próximo deploy.)
- **Corrección:** `get_or_create` (solo crear si falta) o excluir `price` de los `defaults` para servicios existentes.

<a id="biz-05"></a>
### BIZ-05 · ALTO · Fechas de egresos en UTC, no en Bogotá (descuadra el ROI mensual)
- **Dónde:** `apps/cashflow/models.py:210` — `date = models.DateField(auto_now_add=True)`.
- **Problema:** `auto_now_add` usa `date.today()` local del servidor (UTC en Railway). Todo egreso entre 19:00 y 24:00 hora Colombia queda fechado al día siguiente. Impacta el matching mensual del ROI (`apps/roi/services.py:110`), el reporte mensual (`apps/analytics/views.py:340`) y el cuadre contra `DailyClose.date` (que sí usa hora local). Un egreso del 31 de mayo 8pm cae en junio para el ROI.
- **Corrección:** `default=` con función que retorne `timezone.localtime(timezone.now()).date()`.

<a id="biz-06"></a>
### BIZ-06 · ALTO · Doble reserva por condición de carrera (`clean()` es código muerto)
- **Dónde:** `apps/bookings/views.py:247-287`, `apps/bookings/models.py:66`.
- **Problema:** no existe ningún `full_clean()` en el repo → la validación de solape por `duration_minutes` nunca se ejecuta. La única defensa es un check-then-create manual **sin transacción ni lock**: dos requests concurrentes para el mismo barbero a las 10:00 y 10:30 (servicio de 60 min) pasan ambos el chequeo y se insertan; el `UniqueConstraint` solo bloquea la hora de inicio exacta. Igual en `admin_reschedule_booking_view` y el PATCH admin.
- **Corrección:** envolver validación+creación en `transaction.atomic()` con `select_for_update()` sobre las reservas del barbero/fecha, o llamar `full_clean()` dentro de la transacción.

<a id="biz-07"></a>
### BIZ-07 · MEDIO · Rechazar una venta dos veces duplica la devolución de inventario
- **Dónde:** `apps/cashflow/views.py:660-683` (`reject_sale_view`).
- **Problema:** devuelve al stock todos los `InventoryMovement` `out` del booking sin marcarlos ni eliminarlos. Flujo: checkout → rechazo (devuelve OUT#1) → nuevo checkout (crea OUT#2) → segundo rechazo devuelve OUT#1 y OUT#2 → stock inflado.
- **Corrección:** marcar los movimientos revertidos, o vincular movimientos a la `Sale` (no al `Booking`) y revertir solo los de esa venta.

<a id="biz-08"></a>
### BIZ-08 · MEDIO · `pay_barber_view` no excluye a Frank → doble pago
- **Dónde:** `apps/cashflow/views.py:958-1001`.
- **Problema:** `unpaid_commissions_view` excluye a Frank, pero el pago acepta cualquier `barber_id`. Si se paga a Frank por ahí (`is_paid=True`), el cierre igual recalcula su pago desde ventas pendientes sin filtrar `is_paid` (`:121-127`) → Frank cobra dos veces.
- **Corrección:** rechazar el `barber_id` de Frank en `pay_barber_view` y filtrar `is_paid=False` en el cierre.

<a id="biz-09"></a>
### BIZ-09 · MEDIO · Regenerar un snapshot ROI no recalcula meses posteriores
- **Dónde:** `apps/roi/services.py:211-224,311-337`.
- **Problema:** `_get_partner_investment_balance` ordena por `snapshot_id__lt` (pk), no por (year, month). Si se consolidan meses fuera de orden, el "saldo anterior" incluye amortizaciones de meses cronológicamente posteriores. Al regenerar un mes antiguo, las `PartnerMonthlyShare` de meses siguientes no se recalculan; la suma de `amortization_applied` puede superar la inversión total. Solo el `max(balance, 0)` lo disimula.
- **Corrección:** ordenar por (year, month) y regenerar en cascada los snapshots no bloqueados posteriores.

<a id="biz-10"></a>
### BIZ-10 · MEDIO · Reseñas sin validar rango 1–5 (overflow de `Barber.rating`)
- **Dónde:** `apps/bookings/views.py:358-374`.
- **Problema:** `int(request.data.get('barber_rating', 5))` acepta 0, 100, o revienta con `ValueError` (→ 500 vía middleware). Un rating de 100 se guarda y el promedio se escribe en `Barber.rating` = `DecimalField(max_digits=2, decimal_places=1)`; cualquier promedio > 9.9 lanza numeric overflow en PostgreSQL y rompe futuras reseñas de ese barbero.
- **Corrección:** `clamp` 1–5 o validar con serializer antes de crear.

<a id="biz-11"></a>
### BIZ-11 · MEDIO · "Hoy" con fecha naive del servidor en dashboards y bloqueos
- **Dónde:** `apps/analytics/views.py:141-144` (`dashboard_stats_view` con `date.today()` UTC) y `apps/bookings/views.py:44` (`public_blocked_dates_list` con `timezone.now().date()`).
- **Problema:** tras las 7pm hora Colombia, el KPI "ingresos del día" se pone en cero y el Kanban muestra las citas de mañana; el bloqueo público de "hoy" desaparece y deja intentar reservar un día cerrado. Agrava que otros filtros del mismo view sí convierten a Bogotá (zonas mezcladas).
- **Corrección:** `timezone.localtime(timezone.now()).date()` en ambos.

<a id="biz-12"></a>
### BIZ-12 · MEDIO · `finalizar_cita` marca `completed` sin crear venta → cobro imposible
- **Dónde:** `apps/barbers/views.py:618-640`.
- **Problema:** el dashboard del barbero pone `status='completed'` directo. `process_checkout` rechaza reservas `completed` (`cashflow/services.py:37`) → esa cita nunca se factura (sin Sale, comisión ni ingreso). Además `cita.barber.user` (línea 629) lanza `AttributeError` si `barber` es `None`, antes del chequeo IDOR.
- **Corrección:** dirigir el flujo al checkout o usar un estado intermedio; chequear `cita.barber` antes de desreferenciar.

<a id="biz-13"></a>
### BIZ-13 · MEDIO · `production.py` fuerza Cloudinary aunque no haya credenciales
- **Dónde:** `config/settings/production.py` (bloque `STORAGES` final).
- **Problema:** el `if CLOUDINARY_CLOUD_NAME` solo protege el dict `CLOUDINARY_STORAGE`; `STORAGES['default']` se fija incondicionalmente a `MediaCloudinaryStorage`. En local (production es el default de manage.py) todo upload de media falla, contra el fallback a filesystem documentado en CLAUDE.md.
- **Corrección:** mover la asignación de `STORAGES['default']` dentro del `if`.

<a id="biz-14"></a>
### BIZ-14 · MEDIO · Frank contabilizado distinto entre reporte mensual y ROI
- **Dónde:** `apps/analytics/views.py:330-357` vs `apps/roi/services.py:104-127`.
- **Problema:** el reporte mensual excluye la comisión de Frank y confía en el Expense "Pago Diario: Franko", que solo existe tras el cierre diario. Para ventas del mes no cerradas, el costo de Frank no aparece → `net_income` sobreestimado. El ROI usa el criterio inverso (cuenta la Commission, excluye el Expense) → ambos paneles nunca cuadran hasta cerrar todo.
- **Corrección:** unificar criterio (el del ROI es el robusto).

<a id="biz-15"></a>
### BIZ-15 · MEDIO · N+1 severo en el listado de clientes
- **Dónde:** `apps/clients/views.py:38-56` — por cada cliente (hasta 100) 2 queries extra (`latest_booking`, `preferred`) → ~200 queries/request.
- **Corrección:** anotar con `Subquery`/window functions o resolver en dos queries agregadas.

<a id="biz-16"></a>
### BIZ-16 · MEDIO/BAJO · Duplicación de jobs con `--workers 2` (latente)
- **Dónde:** Procfile (gunicorn con 2 workers) + `apps/bookings/apps.py`, `apps/roi/apps.py`.
- **Problema:** cuando se arreglen los guards (BIZ-01/02), ambos workers ejecutan `ready()` → dos `BackgroundScheduler`. `send_upcoming_reminders` marca `reminder_sent` sin lock → recordatorios duplicados. Hoy no ocurre solo porque los schedulers están muertos.
- **Corrección:** un solo proceso "leader" (env var / lock en BD) o mover los jobs a un cron externo de Railway.

<a id="biz-17"></a>
### BIZ-17 · BAJO · Otros hallazgos de backend
- `settings.TESTING` no existe en ningún settings (`apps/bookings/apps.py:21`): el guard anti-scheduler-en-tests es inoperante.
- `can_cancel` (`apps/bookings/models.py:100-111`) permite cancelar hasta el instante de la cita, pero el mensaje dice "menos de 2 horas de anticipación" (`views.py:324,331`): incoherente.
- Mutación de `request.data` inmutable en walk-ins (`apps/bookings/views.py:66-67`): `AttributeError` si llega form-data (QueryDict). Copiar antes de mutar.
- Disponibilidad pública considera reservas `completed` como bloqueantes (`apps/barbers/views.py:112-114` usa `.exclude(status='cancelled')`) mientras la creación usa `status__in=['pending','confirmed']`: pinta ocupado un slot que sí se aceptaría.
- Oversell silencioso de inventario y read-modify-write sin lock (`apps/cashflow/views.py:846-853`, `services.py:120-127`): usar `F('quantity') - x` con `select_for_update`.
- Carrera y código muerto en el cierre diario (`apps/cashflow/views.py:95-114`): `exists()` + `create()` fuera de lock; variable `total_sales` sin usar.
- Export CSV excluye a `operational_admin` (`apps/bookings/views.py:730` usa `role not in ('admin','superadmin')`) mientras el listado JSON lo incluye: Frank exporta solo sus reservas pero las ve todas.
- Aportes de capital sin validar monto (`apps/roi/views.py:200-226`): acepta negativos; la edición sí valida `> 0`.
- Recordatorios escanean toda la tabla de reservas (`apps/bookings/scheduler.py:26-43`): añadir `date__in=[hoy, mañana]`.
- Excepciones silenciadas con `print`/`pass`/`fail_silently=True` en flujos de correo y auditoría: usar `logger.exception`.
- `seed.py:257` — `Partner.objects.exclude(user__in=valid_users).delete()` puede borrar en cascada `PartnerInvestment`/`PartnerMonthlyShare` si cambia el username de un socio; los Partner con `user=None` sobreviven (socios zombis al 50%). Desactivar en vez de borrar.

---

## 3. Sitio público (frontend)

### Bugs

<a id="pub-01"></a>
#### PUB-01 · CRÍTICO · Marcadores de conflicto Git sin resolver en el CSS de producción
- **Dónde:** `static/css/styles.css:226-256` (y `static/js/admin.js:1-19`).
- **Problema:** `<<<<<<< HEAD`, `=======`, `>>>>>>>` commiteados. El CSS se sirve en las 8 páginas públicas; por la recuperación de errores de CSS, el bloque inválido se traga el `@media (max-width: 640px)` completo → los ajustes responsive del FAB en móvil nunca se aplican.
- **Corrección:** resolver el conflicto conservando el bloque responsive.

<a id="pub-02"></a>
#### PUB-02 · CRÍTICO · XSS almacenado en las reseñas del index
- **Dónde:** `templates/public/index.html:1199-1223`.
- **Problema:** `r.comment` y `r.client_name` (entrada pública sin autenticación vía `rate.html` → `add_review_view`) se inyectan con `innerHTML` sin escapar. Un cliente escribe `<img src=x onerror=...>` en su comentario (solo necesita 4-5 estrellas para publicarse) y ejecuta JS en la portada para todos.
- **Corrección:** escapar HTML antes de interpolar o construir nodos con `textContent`.

<a id="pub-03"></a>
#### PUB-03 · ALTO · "[object Object]" como especialidad en /profesionales/
- **Dónde:** `templates/public/profesionales.html:220,241`.
- **Problema:** `b.especialidad || b.specialties || 'Master Barber'`; `/api/barbers/` expone `specialties` como array de objetos Service, nunca `especialidad`. Un array vacío es truthy → el fallback nunca aplica: se muestra `[object Object],[object Object]` o texto vacío.
- **Corrección:** `Array.isArray(b.specialties) && b.specialties.length ? b.specialties.map(s => s.name).join(', ') : 'Master Barber'`.

<a id="pub-04"></a>
#### PUB-04 · ALTO · Enlaces relativos rompen la navegación (404)
- **Dónde:** `templates/public/gallery.html:47`, `services.html:46-47,102`, `index.html:519-550`.
- **Problema:** rutas canónicas `/gallery/`, `/services/`; desde `/gallery/` el enlace `booking.html` resuelve a `/gallery/booking.html` → 404. Flujo roto: Inicio → Profesionales → Galería → "Reserva tu Cita" → 404.
- **Corrección:** usar `{% url 'booking' %}` / rutas absolutas `/booking/` en todos los navs.

<a id="pub-05"></a>
#### PUB-05 · ALTO · `Promise.all` sin retornar → horarios cargando para siempre
- **Dónde:** `templates/public/booking.html:486-496`.
- **Problema:** el `.then` no retorna el `Promise.all`, así que si una sola petición de disponibilidad falla, el rechazo no llega al `.catch` y la UI queda en "Consultando horarios disponibles..." indefinidamente.
- **Corrección:** `return Promise.all(...)` o `Promise.allSettled` para tolerar fallos parciales.

<a id="pub-06"></a>
#### PUB-06 · ALTO · Submit de reserva sin `.catch` ni protección de doble envío
- **Dónde:** `templates/public/booking.html:565-598`.
- **Problema:** `fetch('/api/bookings/')` sin `.catch` (error de red = sin feedback); el botón "Confirmar Reserva" nunca se deshabilita → doble clic = dos POST.
- **Corrección:** deshabilitar el botón con "Enviando...", `.catch` con mensaje inline, re-habilitar en error.

<a id="pub-07"></a>
#### PUB-07 · ALTO · `services.js` es módulo ES cargado como script clásico → SyntaxError
- **Dónde:** `static/js/services.js:77-87`, cargado en `services.html:155`.
- **Problema:** `export function ...` sin `type="module"` → `Uncaught SyntaxError` en cada visita a servicios. Es data hardcodeada obsoleta (código muerto).
- **Corrección:** eliminar el `<script>` y el archivo.

<a id="pub-08"></a>
#### PUB-08 · MEDIO · Bugs adicionales del sitio público
- La página de servicios nunca muestra la descripción real: usa `servicio.features` pero `/api/servicios-nativos/` devuelve `description` (`services.html:115`) → siempre el fallback "Atención premium".
- Fetch de servicios sin `.catch` → "Cargando servicios..." eterno (`index.html:1090-1142`, `booking.html:251-363`).
- Hora de cierre hardcodeada 19:00 (`booking.html:429`) contradice el horario publicado (L-V hasta 8pm, sáb 9pm): bloquea reservas de la misma noche.
- Enlace legal de Habeas Data apunta a `#` (`booking.html:183`, `index.html:946-947`) siendo checkbox obligatorio (Ley 1581 de 2012). Crear el documento y enlazarlo.
- `gallery.js` legado (`static/js/gallery.js:1-35`): segundo listener de click y filtro incompatible; inocuo solo por captura de NodeList vacío. Eliminar.
- (BAJO) `.catch` de profesionales referencia un loader ya removido (`profesionales.html:202,255`) → TypeError; query muerta `HomeView` (`apps/bookings/views.py:33-36`); alt del lightbox nunca se actualiza (`gallery.html:93`); likes de reels solo en `localStorage`, nunca persisten (`reels.html:301-316`).

### Mejoras visuales / UX

<a id="pub-ux"></a>
- **ALTO — Hero de 8.4 MB PNG** (`index.html:560`, `static/images/hero_luxury.png`): imagen LCP; convertir a WebP/AVIF (~200-400 KB) con `fetchpriority="high"`. El video (4.7 MB) hace autoplay en la misma página: darle `preload="none"` + `poster`.
- **ALTO — Tailwind por CDN en producción** (todas las páginas públicas): `cdn.tailwindcss.com` es el compilador JIT (~300 KB JS bloqueante) con warning oficial de no usar en producción y FOUC. Compilar a CSS estático servido por WhiteNoise.
- **ALTO — Contenido esencial invisible en móvil en /profesionales/** (`profesionales.html:233-246`): especialidad, bio, rating y botón "Reservar" con `opacity-0 group-hover:opacity-100`; en táctil no hay hover → el usuario móvil solo ve nombre y foto, sin CTA. Usar `opacity-100 md:opacity-0 md:group-hover:opacity-100`.
- **MEDIO** — Fechas ISO crudas en el wizard (`booking.html:470,558`): formatear con `toLocaleDateString('es-CO', {...})`.
- **MEDIO** — Ortografía: "ENCONTRÁNOS AQUÍ" → "ENCUÉNTRANOS AQUÍ" (`index.html:827`); inglés visible "Sophistication in every cut." (`services.html:63`).
- **MEDIO** — Accesibilidad: hamburguesa sin `aria-label` (`index.html:530`, `profesionales.html:63`), botón mute del video, FAB "30", estrellas de `rate.html:52-69` (solo "★" al lector), botones de reels, iframes de Maps sin `title`.
- **MEDIO** — Sección de reseñas en blanco si el fetch falla (`index.html:1226-1228`): mostrar `#reviews-empty` en el catch.
- **MEDIO** — Autoplay con sonido en reels siempre bloqueado (`reels.html:272`): iniciar muteado y activar sonido con el primer tap.
- **BAJO** — `alert()` con JSON crudo para errores de reserva (`booking.html:595`); navbar inconsistente entre páginas (tres variantes); typo "Barber Cub" en el embed de Maps (`index.html:848`, etc.); `/services/` huérfana (nadie la enlaza); doble envío posible en `rate.html` y buzón de sugerencias.

---

## 4. Panel de administración

### Bugs

<a id="adm-01"></a>
#### ADM-01 · CRÍTICO · XSS almacenado con datos del cliente en casi todo el panel
- **Dónde:** el nombre/email/teléfono del cliente entra por el formulario público (`AllowAny`) y el panel lo pinta con `innerHTML`/template literals sin escapar:
  - `templates/admin/bookings.html:447-465` (además `openCheckout(... '${b.client_name.replace(/'/g,...)}')` escapa `'` pero no `"` ni `<`).
  - `templates/admin/dashboard.html:264-276,437-441` (aprobaciones y kanban).
  - `templates/admin/clients.html:67-79,89-101` (nombre, historial, `viewHistory('${c.phone}')` en `onclick`).
  - `templates/admin/cashflow.html:765-843` (trazabilidad: `client_name`, `service_name`, `notes`).
  - `templates/admin/audit_log.html:236-249` (mensajes de auditoría incluyen nombre del cliente).
- **Riesgo:** un cliente que reserve con nombre `<img src=x onerror=...>` ejecuta JS en la sesión del superadmin.
- **Corrección:** función `esc()` global (como la de `roi_dashboard.html:865`, que sí lo hace bien) aplicada a todo dato dinámico antes de `innerHTML`, o `textContent`.

<a id="adm-02"></a>
#### ADM-02 · CRÍTICO · API de servicios escribible + panel permite a `admin` editar precios
- Mismo backend que [SEC-05](#sec-05). Además la página Configuración (`apps/users/views.py:186`) permite al rol `admin` editar precios, contra el modelo de roles (`can_modify_prices` es solo superadmin).

<a id="adm-03"></a>
#### ADM-03 · CRÍTICO · Endpoint de reservas acepta precio arbitrario (walk-in)
- Mismo que [SEC-01](#sec-01); el modal Walk-in (`bookings.html:879`) manda `price` desde el DOM.

<a id="adm-04"></a>
#### ADM-04 · ALTO · Dashboard usa la fecha del servidor (UTC)
- **Dónde:** `apps/analytics/views.py:140-144` (`date.today()` + `strptime` sin tz). En Railway (UTC), desde las ~7pm Colombia "hoy" es mañana: el KPI "Ingresos Hoy" (que `dashboard.html:211-227` sobreescribe sobre el valor correcto de Django) va a 0 y el Kanban muestra el día equivocado. Mismo patrón en `barbers.html:616,816,914` (`new Date().toISOString()...`).
- **Corrección:** `timezone.localtime(timezone.now()).date()` en el backend y el truco del offset en JS (como ya hace `bookings.html:824-828`).

<a id="adm-05"></a>
#### ADM-05 · ALTO · Checkout: campos fuera del `<form>` → validación y reset rotos
- **Dónde:** `templates/admin/bookings.html:213-347`. El cuerpo del modal (método de pago `required`, propina, descuento, notas) está **fuera** de `<form id="checkout-form">` (línea 339, solo envuelve el footer).
- **Consecuencias:** (a) el `required` del método de pago nunca se valida — se confirman cobros sin método (el backend lo deja `None`, `cashflow/services.py:45`); (b) `closeCheckout()` llama `form.reset()` que no resetea nada → propina/descuento/notas del cobro anterior se arrastran al siguiente.
- **Corrección:** mover el cuerpo dentro del form, o resetear campo a campo en `openCheckout()` y validar `payment_method` en JS y backend.

<a id="adm-06"></a>
#### ADM-06 · ALTO · Calendario muestra acciones que el backend rechaza en silencio
- **Dónde:** `templates/admin/calendar.html:56-58,161`. Muestra Confirmar/Completar/Cancelar y habilita drag&drop a **todos los roles**, pero el backend solo permite cambiar estado a superadmin (`apps/bookings/views.py:504-506`) y fecha/hora a operational/superadmin (`:524-527`). Para los demás el PATCH devuelve 200 ignorando los campos → el evento queda movido en pantalla pero no en la BD (`info.revert()` nunca dispara). `updateBookingStatus` no mira errores 403/409.
- **Corrección:** condicionar botones/drag al rol (como `bookings.html`) y mostrar `data.error` cuando `!r.ok`; en backend devolver 403 en vez de ignorar campos.

<a id="adm-07"></a>
#### ADM-07 · ALTO · Barbero puede cobrar reservas ajenas
- Manifestación en el panel de [SEC-08](#sec-08): el botón "COBRAR" (`bookings.html:464`) aparece en todas las filas; el endpoint no valida propiedad.

<a id="adm-08"></a>
#### ADM-08 · ALTO · Panel de aprobaciones roto para `admin`
- Mismo que [SEC-09](#sec-09).

<a id="adm-09"></a>
#### ADM-09 · ALTO · Reservas y calendario truncados a 200 sin aviso
- **Dónde:** `apps/bookings/views.py:469` — `queryset[:200]` con orden descendente. Con más de 200 reservas, la tabla (grupo "Anteriores") y el calendario pierden el histórico sin indicarlo.
- **Corrección:** paginación real (DRF ya tiene `PAGE_SIZE=50`) o filtrar por rango de fechas por defecto e indicar "mostrando 200 de N".

<a id="adm-10"></a>
#### ADM-10 · MEDIO · Bugs adicionales del panel
- **Tres fórmulas distintas de "Ingreso Neto" en Caja** (`apps/users/views.py:253`, `apps/cashflow/views.py:471-483` y `:150-158`): los KPI muestran un neto que el JS reemplaza por otro; el modal de confirmación de cierre (`cashflow.html:458`) muestra el neto stale del render. Unificar en una sola función en `cashflow/services.py`.
- **Botón "Cerrar caja" queda muerto** (`cashflow.html:304,985`): se deshabilita con el conteo server-side y el listener solo se registra `if (!btnOpen.disabled)`; si entran ventas tras el auto-refresh sigue inservible hasta recargar. Además `pending_sales_count` incluye ventas de inventario mientras el sub-KPI JS cuenta solo servicios.
- **Hora del cierre en UTC** (`apps/cashflow/views.py:294`): `closed_at.strftime()` sin `timezone.localtime` → el modal muestra +5h vs la tarjeta del historial en hora local.
- **Acciones sin manejo de error** (fallan en silencio): `quickStatus` (`bookings.html:549-556`), `toggleActive` (`reels.html:211-217`), `deleteBlockedDate`/`deleteService` (`settings.html:291-341`), subida de foto (`gallery.html:156-163`), `deleteBarber` (`barbers.html:363-371`).
- **Menú "Acciones" recortado por overflow** (`bookings.html:110-111` vs dropdown absolute `:477`): en filas finales y móvil queda cortado.
- **Montos sin separador de miles**: DRF serializa `DecimalField` como string, y `"25000".toLocaleString()` es no-op. Afecta Reservas (`bookings.html:460`), Calendario (`calendar.html:203`), Clientes (`clients.html:72,98`), KPI de dashboard tras cargar API. Usar `Number(x).toLocaleString('es-CO')`.
- **"Gráficas" calcula ingresos distinto que Caja** (`apps/analytics/views.py:23-47` suma `Booking.price` de completed vs `Sale.final_price` aprobadas): cifras diferentes por página.
- **Galería/Reels: sidebar lo oculta a barberos pero el backend lo permite** — mismo que [SEC-07](#sec-07).
- **Login: `password.strip()`** (`apps/users/views.py:19`) rechaza contraseñas con espacios; el username se fuerza a minúsculas (`:18`), rompiendo cuentas con mayúsculas.
- **Clientes sin estado vacío/carga ni `.catch`** (`clients.html:59-80`).

<a id="adm-11"></a>
#### ADM-11 · BAJO · Otros hallazgos del panel
- `</div>` extra en `bookings.html:132`; código muerto en `roi_dashboard.html:560`, `audit_log.html:165-167`, `bookings.html:582-595` (`deleteAllBookings` a endpoint deshabilitado).
- Polling de notificaciones sin `catch` y badge que no se apaga al bajar a 0 (`base_admin.html:320-324`).
- Apóstrofos rompen `onclick`: `inventory.html:382` (`openAdjustModal(... '${item.name}' ...)`), `settings.html:252`.
- Egresos limitado a 50 sin indicarlo (`apps/users/views.py:283`, `expenses.html:21`).
- Años hardcodeados 2024-2027 en Reportes (`reports.html:28-31`).
- Estadísticas de inventario incoherentes (`inventory.html:421-422`): stock 0 no cuenta ni en "OK" ni en "Bajo".
- `renderBlockedDates()` llamado dos veces al cargar (`settings.html:175,206`).
- Checkbox "Recuérdame" del login no hace nada (`login.html:316`).
- Un servicio borrado a mano resucita en el próximo deploy por `seed.py` (relacionado con [BIZ-04](#biz-04)).

### Mejoras visuales / UX

<a id="adm-ux"></a>
- **ALTO — Feedback unificado tras acciones**: el panel mezcla `alert()` nativo, modales custom, toasts de Django y acciones sin feedback. Crear un componente toast global en `base_admin.html` (ya existe el de Django messages, reutilizarlo desde JS).
- **ALTO — Tabla de Reservas en móvil**: 9 columnas + dropdown dentro de `overflow-x-auto` (`bookings.html:110-131`). Caja ya resolvió esto con cards mobile-first (`cf-row`); replicar en Reservas y Clientes.
- **MEDIO — Estados de carga faltantes** en Reservas, Clientes y Reportes (inventario y audit_log sí los tienen).
- **MEDIO — Estado de reserva en inglés** en el modal del calendario (`calendar.html:204` pinta `data.status` crudo); reutilizar el mapa de badges de `bookings.html:409-414`.
- **MEDIO — Formato de fechas/horas inconsistente**: chart ISO "2026-04" (`charts.html:89`) vs "Abr 2026" en ROI; heatmap en 24h vs 12h AM/PM en el resto; detalle del cierre en UTC.
- **MEDIO — Ortografía/redacción**: "Confirmar Reagendo" → "Confirmar reagendamiento" (`bookings.html:1098`); "Más adelantadas" → "Próximas" (`bookings.html:432`); "Servicio Manual (Frank)" hardcodea un nombre propio en el sidebar (`base_admin.html:91`).
- **MEDIO — Charts mejorables**: donut sin datos deja canvas vacío y con >8 servicios se quedan sin color (`charts.html:105-119`); eje Y con montos COP completos, abreviar a "$1,2M"; contraste pobre en el heatmap a intensidad alta.
- **BAJO — Inconsistencias de estilo** entre páginas (radios de borde, doble padding en `reviews.html:7`, botones a veces planos y a veces gradiente); confirmaciones inconsistentes (`confirm()` nativo vs modal custom); `getCSRF()` copiado en ~8 templates (mover a `static/js/admin.js`); modal de rechazo duplicado (`dashboard.html` y `cashflow.html`).

---

## Plan de remediación sugerido

**Fase 1 — Crítico (explotable hoy):**
1. [SEC-01](#sec-01)/[ADM-03](#adm-03) precio de reserva manipulable → forzar `service.price` en el servidor.
2. [SEC-05](#sec-05)/[ADM-02](#adm-02) API de servicios abierta → permiso de escritura restringido a superadmin.
3. [SEC-03](#sec-03) `/init-soporte/` + [SEC-02](#sec-02) credenciales en `seed.py` → eliminar/proteger endpoint, mover claves a env, rotar todo.
4. [SEC-04](#sec-04) cancelación por ID → exigir `signed_id`.
5. [SEC-06](#sec-06) `SECRET_KEY` → exigir la variable en producción.
6. [PUB-02](#pub-02)/[ADM-01](#adm-01) XSS almacenado → función `esc()` global en público y panel.
7. [PUB-01](#pub-01) marcadores de conflicto Git en CSS/JS.

**Fase 2 — Operación y finanzas:**
8. [BIZ-01](#biz-01)/[BIZ-02](#biz-02) guards de schedulers → recordatorios y consolidación ROI.
9. [BIZ-03](#biz-03) ciclo eliminar-recerrar (doble pago Frank), [BIZ-07](#biz-07) doble restock, [BIZ-08](#biz-08) doble pago vía `pay_barber`.
10. [BIZ-05](#biz-05)/[BIZ-11](#biz-11) fechas UTC → hora local Bogotá en egresos y dashboards.
11. [BIZ-04](#biz-04) `seed.py` revierte precios → `get_or_create`.
12. [BIZ-06](#biz-06) doble reserva → transacción + lock.

**Fase 3 — UX y robustez:**
13. Manejo de error unificado (toasts) en público y panel; formato de montos/fechas; estados de carga/vacío.
14. Responsive: tablas mobile-first, contenido de /profesionales/ visible en táctil, hero optimizado, Tailwind compilado.
15. Limpieza: código muerto (`services.js`, `gallery.js`, endpoints deshabilitados), N+1 de clientes, `settings.TESTING`.

---

*Documento generado por auditoría automatizada de solo lectura. Cada hallazgo cita archivo:línea para verificación directa. Se recomienda confirmar cada corrección con una prueba manual del flujo afectado antes de desplegar.*
