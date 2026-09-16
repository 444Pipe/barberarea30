# Plan de conciliación de caja — Área 30 Barber Club

Fecha: 15 de septiembre de 2026
Estado: **fases 1 a 4 implementadas, revisadas y probadas localmente** (37 pruebas en verde).
Pendiente: correr la auditoría contra producción, confirmar D1 con el dueño,
desplegar, y ejecutar la fase 5 (conteo físico).
Origen: reporte del dueño (Camilo) sobre diferencias entre el "Debe haber" del control de caja y la página de Egresos, y solicitud de separar "pago a barberos" y "materiales" del gasto del día a día.

---

## 1. Resumen ejecutivo

El control de caja (`/admin-panel/cashflow/`, tarjeta "Efectivo / Transferencia") y la página de Egresos (`/admin-panel/expenses/`) **no suman la misma lista de cosas**. Ninguna está "mal sumada"; cada una tiene su propio universo:

| Salida de dinero | Modelo que la guarda | La resta la caja | La lista Egresos |
| --- | --- | --- | --- |
| Gasto normal (desinfectante, boletas) | `Expense` | sí | sí |
| Pago Diario: Franko (cierre del día) | `Expense` automático, tipo `variable` | sí | sí |
| Materiales Servicio (color, tinte) | `Expense` automático, tipo `variable` | **no** (excluido a propósito) | sí |
| Vale / adelanto (botón "Dar vale") | `BarberAdvance` | sí (si tiene `payment_source`) | **no** |
| Liquidación a barberos no-Frank | `BarberPayment` con `daily_close=None` | sí (siempre como efectivo) | **no** |
| Retiros y traslados | `CashMovement` | sí | **no** |

Tres de esas diferencias cuestan dinero real:

1. **Materiales de servicio**: los formularios prometen que se descuentan de la caja y Egresos los muestra como salida en efectivo, pero `compute_cash_box` los excluye. El "Debe haber" queda inflado.
2. **Vales escritos como egreso** ("Vale Franko"): salen de la caja pero no bajan el saldo de Frank en el ledger. El cierre le sugiere pagar completo.
3. **Liquidaciones a barberos no-Frank**: siempre se guardan como efectivo aunque se hayan pagado por transferencia.

Y una petición funcional: el dueño quiere ver aparte cuánto va a **materiales**, cuánto al **día a día** y cuánto a **pago a barberos**. Hoy todo cae en "Gasto Variable".

La solución tiene cinco fases, cada una desplegable y verificable por separado:

| Fase | Nombre | Qué entrega | Esfuerzo | Riesgo |
| --- | --- | --- | --- | --- |
| 1 | Auditoría | Comando que mide el descuadre con datos de producción | ½ día | ninguno |
| 2 | Fugas | Materiales en la caja, vales solo por "Dar vale", fuente en liquidaciones | 1–2 días | medio |
| 3 | Categorías | Tipos `materials` y `barber_payment`, reclasificación del historial, ROI/reportes por tipo | 1 día | bajo |
| 4 | Una verdad | Egresos lista TODAS las salidas y su suma iguala la de la caja, con prueba automática | 1–2 días | bajo |
| 5 | Cierre | Conteo físico, punto de partida, regla de uso con el equipo | ½ día | — |

---

## 2. Mapa de datos: modelos, campos y relaciones

Todo vive en `apps/cashflow/models.py` salvo donde se indica.

### 2.1 `PAYMENT_SOURCE_CHOICES`

```python
PAYMENT_SOURCE_CHOICES = [('cash', 'Efectivo'), ('transfer', 'Transferencia')]
```

Lo usan `Expense.payment_source`, `BarberPayment.payment_source`, `BarberAdvance.payment_source` (este último admite `''` = vale histórico que no toca caja), `CashMovement.source` y `CashMovement.to_source`.

### 2.2 `Sale` (entrada de dinero)

- `final_price`, `tip_amount`, `payment_method` (FK a `PaymentMethod`, slugs `efectivo` / `transferencia`; `NULL` cuenta como efectivo).
- `approval_status` (`pending` / `approved`). **Solo las aprobadas entran a la caja.**
- `included_in_daily_close` (FK a `DailyClose`).
- La comisión se crea en `Commission` con `basis_amount`, `commission_amount`, `tip_amount`, `total_earnings`.

### 2.3 `InventorySale` (entrada de dinero)

- `total_price`, `payment_method`. Entra a la caja igual que una venta.

### 2.4 `Expense` (salida de dinero, la única que ve la página Egresos)

| Campo | Tipo | Notas |
| --- | --- | --- |
| `description` | char(200) | Prefijos reservados: `Pago Diario: Franko` y `Materiales Servicio: <cliente> (venta #<id>)` |
| `amount` | decimal | COP sin centavos |
| `expense_type` | char(20) | Hoy: `fixed`, `variable`, `inventory`. Default `variable` |
| `payment_source` | char(10) | `cash` / `transfer`. Default `cash` |
| `date` | date | Fecha local Bogotá. Editable. **No** es la fecha de registro |
| `created_at` | datetime | Fecha de registro. La caja acota el período por este campo |
| `registered_by` | FK User | |
| `included_in_daily_close` | FK DailyClose | Lo llena el cierre diario |
| `notes`, `image` | | Soporte / foto |

Quién crea `Expense` hoy:

| Punto de creación | Archivo:función | `expense_type` | `payment_source` |
| --- | --- | --- | --- |
| Formulario Egresos | `apps/cashflow/views.py:add_expense_view` (POST `/api/admin/cashflow/expenses/`) | lo elige el usuario; `operational_admin` solo puede `variable` | lo elige el usuario |
| Cierre diario, pago a Frank | `apps/cashflow/views.py:daily_close_view` (~línea 257) | `variable` | `frank_pay_source` del modal |
| Reproceso de cierres | `apps/cashflow/views.py:fix_frank_history_view` (~línea 1341) y `management/commands/fix_frank_history.py:65` | `variable` | default `cash` |
| Checkout con materiales | `apps/cashflow/services.py:process_checkout` (~línea 993) | `variable` | **no se envía → default `cash`** |

Quién lee `Expense` por prefijo de descripción (frágil, a reemplazar por tipo en la fase 3):

- `services.py:compute_cash_box` y `compute_cash_box_detail` → excluyen `MATERIALS_EXPENSE_PREFIX`.
- `services.py:is_materials_expense` → usado por `daily_close_detail_view` y `live_cashflow_detail_view` para el rubro "Materiales".
- `views.py:delete_daily_close_view` → borra `description__startswith='Pago Diario: Franko'` del cierre.
- `views.py:reject_sale_view` (~línea 1240) → borra `description__endswith='(venta #<id>)'` con `expense_type='variable'`.
- `views.py:edit_expense_view` → prohíbe escribir esos patrones a mano.
- `apps/roi/services.py` → `FRANK_DAILY_EXPENSE_DESC = 'Pago Diario: Franko'` excluido de egresos operativos.
- `apps/analytics/views.py` (~línea 361) → mismo exclude para el neto mensual.
- `templates/admin/expenses.html` → candado "egreso automático del sistema" si contiene `Pago Diario: Franko` o `(venta #`.

### 2.5 `BarberAdvance` (vale / adelanto)

- `barber`, `amount`, `reason`, `payment_source` (`''` = histórico, no toca caja), `is_settled`, `settled_in_daily_close`, `settled_in_payment`, `created_at`.
- Se crea en `views.py:register_barber_advance_view` (POST `/api/admin/cashflow/barber-payments/<barber_id>/advance/`). Pide `payment_source` desde el commit `7527ed7` (27 ago 2026).
- Entra al ledger de Frank (`services.py:compute_frank_ledger`) y a la caja. **No** es un `Expense`.

### 2.6 `BarberPayment` (pago real a un barbero)

- `barber`, `daily_close` (Frank: no nulo; resto: nulo), `expense` (FK al `Expense` "Pago Diario" en el caso de Frank), `amount`, `payment_source` (default `cash`), `created_at`.
- Frank: lo crea `daily_close_view`, enlazado a su `Expense`. La caja lo **omite** (`expense__isnull=True`) porque ya cuenta el `Expense`.
- Resto: lo crea `views.py:pay_barber_view` (POST `/api/admin/cashflow/barber-payments/<barber_id>/pay/`). **No recibe `payment_source`** → siempre `cash`. La caja lo cuenta como salida en efectivo.

### 2.7 `CashMovement` (inyección, retiro, traslado, ajuste)

- `kind`, `source`, `to_source`, `amount`, `cash_cut` (nulo = del período en curso). Método `effect_on(box)` devuelve el signo sobre cada caja.

### 2.8 `CashCut` (corte de caja)

- Define el **período en curso**: desde `closed_at` del último corte hasta ahora. Guarda `opening_cash` / `opening_transfer`.
- `services.py:cash_period_bounds()` devuelve `(period_start, opening_cash, opening_transfer)`. Sin cortes, `period_start=None` y se cuenta todo el histórico.

### 2.9 `DailyClose` (cierre de jornada)

- Totales del día: `total_sales`, `total_inventory_sales`, `total_tips`, `total_commissions`, `total_expenses`, `net_income`.
- `total_expenses` toma **todos** los `Expense` con `included_in_daily_close IS NULL` al momento del cierre (fijos, variables, de cualquier fuente), incluido el "Pago Diario" recién creado.

### 2.10 ROI (`apps/roi/`)

- `MonthlyROISnapshot.total_fixed_expenses` = `expense_type='fixed'`.
- `MonthlyROISnapshot.total_operational_expenses` = `expense_type IN ('variable','inventory')` excluyendo "Pago Diario: Franko".
- `apps/roi/services.py` (~línea 113–125) hace ese cálculo. **Un tipo nuevo que no esté en esas listas desaparece del ROI en silencio.** Por eso la fase 3 toca este archivo obligatoriamente.

---

## 3. Cómo se calcula hoy el "Debe haber"

`apps/cashflow/services.py:compute_cash_box(reference_date=None, exclude_cut_id=None)`, y su gemelo con historial `compute_cash_box_detail()`.

Para cada caja (`cash`, `transfer`):

```
apertura = opening_* del último CashCut (0 si no hay)
entradas = Σ Sale aprobadas (final_price + tip_amount) con ese método
         + Σ InventorySale con ese método
         + movimientos manuales con efecto positivo (inyección, traslado entrante, ajuste +)
salidas  = Σ Expense con payment_source=fuente  EXCLUYENDO description LIKE 'Materiales Servicio:%'
         + Σ BarberPayment con payment_source=fuente y expense IS NULL   (no-Frank)
         + Σ BarberAdvance con payment_source=fuente                      (vales con fuente)
         + movimientos manuales con efecto negativo (retiro, traslado saliente, ajuste −)
saldo    = apertura + entradas − salidas
```

Acotación temporal: `created_at > period_start` en todos los modelos. Los `CashMovement` se acotan por `cash_cut IS NULL`.

Diferencia importante con la página Egresos: `admin_expenses_view` (`apps/users/views.py:360`) filtra por `Expense.date` (fecha del egreso, editable), no por `created_at`, y sin filtro muestra los últimos 50.

---

## 4. Hallazgos con evidencia

### H1 · Materiales de servicio no se descuentan de la caja (alta)

- Formulario de servicio manual (`templates/admin/manual_service.html:96`): "Gasto que se descontará de la caja (asumido 50/50)".
- Checkout (`templates/admin/bookings.html:312`): "Se registrará como Egreso".
- `process_checkout` crea el `Expense` con `payment_source` por defecto `cash` → Egresos lo muestra como "💵 Efectivo".
- `compute_cash_box` y `compute_cash_box_detail` lo excluyen (`services.py:453` y `:550`).
- Pantallas del 15/09: ventas #910 (`$28.000`) y #911 (`$143.000`) → `$171.000` que Egresos muestra y la caja no resta.

### H2 · Vales registrados como egreso libre (alta)

- Egresos "Vale Franko" (`$20.000`) y "Vale Franko - Vilma" (`$24.000`) del 11/09, registrados por `frank`, tipo `variable`.
- `add_expense_view` acepta cualquier descripción.
- `compute_frank_ledger` solo resta `BarberAdvance`. Esos egresos no bajan el saldo de Frank; el cierre sugiere pagar completo → doble entrega salvo ajuste manual.

### H3 · Liquidaciones a barberos no-Frank siempre en efectivo (alta)

- `pay_barber_view` crea `BarberPayment` sin `payment_source` (`views.py:1839`). El modal en `cashflow.html:1763` es un `confirm()` sin selector.

### H4 · Egresos no muestra vales, liquidaciones ni retiros (media)

- `admin_expenses_view` solo lista `Expense`. Sin filtro por fuente ni por período de caja.

### H5 · Categorías insuficientes (media, petición del dueño)

- `EXPENSE_TYPES` = `fixed`, `variable`, `inventory`. "Pago Diario" y "Materiales" son `variable`.

### H6 · `date` vs `created_at` (baja)

- Un egreso registrado hoy con `date` de la semana pasada entra en la caja del período actual pero puede quedar fuera del filtro de Egresos, y viceversa.

---

## 5. Decisiones y supuestos

| # | Decisión | Estado |
| --- | --- | --- |
| D1 | Los materiales de un servicio **sí** salen de la caja, en la fuente que se indique al confirmar la venta. Se agrega la opción "no salió de caja" para el caso en que Frank pone el insumo o sale de stock ya pagado. | Recomendada; pendiente de confirmación del dueño antes de desplegar fase 2 |
| D2 | Los adelantos a barberos se registran **solo** con "Dar vale". El formulario de Egresos rechaza descripciones que parezcan un vale. | Aprobada |
| D3 | Los egresos históricos tipo "Vale …" se convierten a `BarberAdvance` **solo con lista aprobada por el dueño** (salida de la fase 1). No se recalcula nada más hacia atrás. | Pendiente de lista |
| D4 | Se agregan dos tipos: `materials` (Materiales / insumos de servicio) y `barber_payment` (Pago a barberos). El historial se reclasifica por prefijo de descripción. | Aprobada |
| D5 | `barber_payment` manual lo puede elegir solo un superadmin (bonos, pagos fuera de liquidación) y **no** toca el ledger de ningún barbero. El sistema lo asigna automáticamente al "Pago Diario: Franko". | Aprobada, **con corrección**: ver D5b |
| D5b | Un `barber_payment` manual **sí cuenta** como gasto operativo en el ROI y en el neto mensual. Solo se descuenta el "Pago Diario: Franko" automático, cuyo costo ya viaja en la Commission de Frank. La versión anterior excluía la categoría entera, y eso dejaba los bonos fuera del neto sin que nadie lo notara: los socios se habrían repartido una utilidad inexistente. Para que el criterio sea seguro, la descripción "Pago Diario: Franko" es un patrón reservado que ni `add_expense_view` ni `edit_expense_view` dejan escribir a mano. | Corregida durante la implementación |
| D6 | `materials` manual lo puede elegir también `operational_admin` (compra puntual de un insumo para un servicio). La compra de stock sigue siendo `inventory` (solo superadmin). | Aprobada |
| D7 | Los vales anteriores al 27/08/2026 (`payment_source=''`) siguen sin tocar la caja. | Se mantiene |
| D8 | La fórmula del neto, el ROI y el 50% de Frank **no cambian**. Solo cambia qué resta la caja y cómo se clasifica cada salida. | Se mantiene |
| D9 | Toda migración de datos es idempotente (se puede correr dos veces) porque `seed.py` y `migrate` corren en cada arranque de Railway. | Regla |

---

## 6. Fase 1 — Auditoría con datos de producción

**Objetivo:** entregarle al dueño una cifra: "la caja muestra X; con las correcciones mostraría Y; la diferencia se explica por…". Sin tocar datos.

### 6.1 Nuevo comando `audit_cash_box`

Archivo: `apps/cashflow/management/commands/audit_cash_box.py`

```
python manage.py audit_cash_box            # período de caja en curso (desde el último corte)
python manage.py audit_cash_box --all      # todo el histórico
python manage.py audit_cash_box --json     # salida en JSON para adjuntar
```

Secciones de salida:

1. **Período**: `period_start`, apertura efectivo/transferencia, último corte y quién lo hizo.
2. **Caja actual** (`compute_cash_box()` tal cual): entradas, salidas, saldo por fuente.
3. **Materiales excluidos**: cada `Expense` con prefijo `Materiales Servicio:` del período, con `date`, `amount`, `payment_source`, venta asociada. Subtotal por fuente.
4. **Egresos que parecen vale**: `Expense` cuya descripción cumple `(?i)\b(vale|adelanto|pr[eé]stamo)\b` y que no es del sistema. Muestra `registered_by`, `date`, `amount`, `payment_source`, si está en un cierre.
5. **Liquidaciones con fuente por defecto**: `BarberPayment` con `daily_close IS NULL` del período, `amount`, `payment_source`, `created_by`, `notes`.
6. **Egresos con fecha distinta a la de registro**: `Expense` donde `date != localdate(created_at)`.
7. **Caja corregida**: misma fórmula pero incluyendo materiales según su `payment_source`. Diferencia por fuente.

Implementación: reutiliza `cash_period_bounds()` y `compute_cash_box()`; no duplica la fórmula, solo suma los materiales aparte y los presenta. Sin escrituras.

### 6.2 Ejecución

- En Railway: `railway run python manage.py audit_cash_box` (o desde el shell del servicio).
- Se guarda la salida en un archivo con fecha y se comparte con el dueño junto con la pregunta D1.
- Resultado esperado: lista de egresos "Vale …" a convertir (entrada de D3) y confirmación de D1.

---

## 7. Fase 2 — Cerrar las tres fugas

### 7.1 Materiales entran a la caja según su fuente

**Modelo** (`apps/cashflow/models.py`):

```python
EXPENSE_SOURCE_CHOICES = PAYMENT_SOURCE_CHOICES + [('none', 'No salió de caja')]

class Expense(models.Model):
    payment_source = models.CharField(
        max_length=10, choices=EXPENSE_SOURCE_CHOICES, default='cash',
        help_text='De dónde salió el dinero: efectivo, transferencia o ninguna '
                  '(insumo que no salió de la caja, p. ej. lo puso el barbero).'
    )
```

Migración `0016_expense_payment_source_none.py`: `AlterField` (solo cambia `choices`; sin cambio de columna). No requiere autocuración en `seed.py`.

**Servicio** (`apps/cashflow/services.py`):

- `compute_cash_box.outflow(source)`: quitar `.exclude(description__startswith=MATERIALS_EXPENSE_PREFIX)`. El filtro `payment_source=source` ya deja fuera los `none`.
- `compute_cash_box_detail.build()`: quitar el mismo `.exclude(...)`. En la fila, `sub` pasa a `'Materiales de servicio'` cuando `is_materials_expense(...)` (en fase 3 será por tipo).
- `process_checkout(...)`: nuevo parámetro `materials_source='cash'`. Validar en `('cash','transfer','none')`. El `Expense` de materiales se crea con `payment_source=materials_source`.
- Actualizar el docstring de `compute_cash_box` (hoy dice que los materiales se excluyen).

**Vista** (`apps/cashflow/views.py:checkout_booking_view`): leer `data.get('frank_materials_source', 'cash')`, validar y pasar a `process_checkout`. Solo cuando `can_send_frank_costs`.

**Templates**:

- `templates/admin/bookings.html` (bloque "MATERIALES FRANK", ~línea 299): agregar `<select id="checkout-materials-source">` con Efectivo / Transferencia / No salió de caja. Texto bajo el campo: "Se registrará como egreso de materiales y se descuenta de la caja elegida". En `submitCheckout` (~línea 834) enviar `frank_materials_source`.
- `templates/admin/manual_service.html:96`: cambiar el texto a "Se registrará como egreso de materiales al confirmar la venta; ahí se indica de qué caja salió". El servicio manual solo guarda el costo en `Booking.manual_materials_cost`; la fuente se decide en el checkout.

**Página Egresos**: en el formulario de registro y en el modal de edición, agregar la opción "No salió de caja" al `<select name="payment_source">`, visible solo para superadmin (evita que se use para esconder salidas). `add_expense_view` y `edit_expense_view` validan contra `('cash','transfer','none')` y rechazan `none` si el rol es `operational_admin`.

**Efecto sobre datos existentes**: los `Expense` de materiales anteriores tienen `payment_source='cash'` y, al desplegar, **pasan a restar de la caja**. Eso es intencional (D1) y hace bajar el "Debe haber" de efectivo en el total de materiales del período. Se comunica al dueño con la cifra de la fase 1 **antes** de desplegar.

### 7.2 Vales solo por "Dar vale"

**Servicio** (`apps/cashflow/services.py`):

```python
import re
ADVANCE_LIKE_RE = re.compile(r'(?i)\b(vale|vales|adelanto|adelantos|pr[eé]stamo|prestamo)\b')

def looks_like_advance(description):
    return bool(ADVANCE_LIKE_RE.search(description or ''))
```

**Vistas** (`apps/cashflow/views.py`):

- `add_expense_view`: si `looks_like_advance(description)` → `400` con `{'error': 'Los adelantos a barberos se registran con el botón "Dar vale" en Caja, para que se descuenten de su saldo. No los registres como egreso.', 'code': 'advance_like'}`.
- `edit_expense_view`: misma validación sobre `new_description`.

**Template** (`templates/admin/expenses.html`): mostrar el error del servidor tal cual y agregar un enlace "Ir a Dar vale" que abre `/admin-panel/cashflow/#pagos-barberos` cuando `code === 'advance_like'`.

**Reparación de datos (D3)** — comando `convert_expense_to_advance`:

```
python manage.py convert_expense_to_advance --expense-id 123 --barber-id 4 [--dry-run]
```

- Crea `BarberAdvance(barber, amount=expense.amount, reason=expense.description, payment_source=expense.payment_source, created_by=expense.registered_by)` y fija `created_at = expense.created_at` con `update()` para que caiga en el mismo período.
- Elimina el `Expense`.
- Si el `Expense` estaba en un `DailyClose`, se deja una nota en el log de auditoría (`log_audit`) indicando que `DailyClose.total_expenses` conserva el valor histórico. No se recalcula el cierre.
- El efecto sobre la caja es neutro (sale un `Expense` en efectivo, entra un `BarberAdvance` en efectivo). El efecto sobre el ledger de Frank es que su saldo baja en ese monto, que es lo correcto.
- Se corre solo con la lista aprobada por el dueño.

### 7.3 Fuente en la liquidación a barberos no-Frank

**Vista** (`apps/cashflow/views.py:pay_barber_view`):

- Leer `payment_source = (request.data.get('payment_source') or '').strip()`. Si no está en `('cash','transfer')` → `400` "Indica si el pago se hizo en efectivo o por transferencia."
- `BarberPayment.objects.create(..., payment_source=payment_source, ...)`.
- Incluir la fuente en el mensaje de auditoría y en la respuesta.

**Template** (`templates/admin/cashflow.html`):

- Reemplazar el `confirm()` de `payBarber` por un modal `cf-modal-pay` con el mismo patrón que `cf-modal-advance`: monto neto en grande, `<select id="cf-pay-source">` Efectivo / Transferencia, botón "Liquidar". Enviar `{ payment_source }` como JSON con `Content-Type: application/json`.
- En `barber_payment_detail_view` (`views.py`) y su render (`cashflow.html` ~línea 2180) mostrar "Efectivo" / "Transferencia" junto a cada pago.

**Datos existentes**: los `BarberPayment` anteriores conservan `cash`. Si la fase 1 muestra alguno pagado por transferencia, se corrige con `update()` puntual con aprobación del dueño.

### 7.4 Pruebas de la fase 2 (`apps/cashflow/tests.py`)

- `test_materiales_en_efectivo_restan_de_la_caja`: checkout con `frank_materials_cost=50000, frank_materials_source='cash'` → `compute_cash_box()['cash_out']` incluye 50.000.
- `test_materiales_sin_fuente_no_tocan_la_caja`: `materials_source='none'` → no aparece en ninguna caja pero sí en `Expense`.
- `test_egreso_que_parece_vale_se_rechaza`: POST con descripción "Vale Franko" → 400 con `code='advance_like'`.
- `test_liquidar_por_transferencia_sale_de_la_caja_de_transferencia`: POST pay con `payment_source='transfer'` → `transfer_out` sube, `cash_out` no.
- `test_liquidar_sin_fuente_falla`: POST sin `payment_source` → 400.

---

## 8. Fase 3 — Categorías: materiales y pago a barberos

### 8.1 Modelo

```python
class Expense(models.Model):
    TYPE_FIXED = 'fixed'
    TYPE_VARIABLE = 'variable'
    TYPE_INVENTORY = 'inventory'
    TYPE_MATERIALS = 'materials'
    TYPE_BARBER_PAYMENT = 'barber_payment'
    EXPENSE_TYPES = [
        (TYPE_FIXED, 'Fijo (Arriendo, Servicios, Nómina)'),
        (TYPE_VARIABLE, 'Variable (Día a día)'),
        (TYPE_INVENTORY, 'Compra de Inventario'),
        (TYPE_MATERIALS, 'Materiales / insumos de servicio'),
        (TYPE_BARBER_PAYMENT, 'Pago a barberos'),
    ]
```

`max_length=20` ya alcanza para `barber_payment` (14 caracteres).

### 8.2 Migración `0017_expense_types_materials_barber_payment.py`

1. `AlterField` de `expense_type` con las nuevas `choices`.
2. `RunPython` idempotente:

```python
def forwards(apps, schema_editor):
    Expense = apps.get_model('cashflow', 'Expense')
    Expense.objects.filter(description__startswith='Materiales Servicio:').exclude(expense_type='materials').update(expense_type='materials')
    Expense.objects.filter(description__startswith='Pago Diario: Franko').exclude(expense_type='barber_payment').update(expense_type='barber_payment')

def backwards(apps, schema_editor):
    Expense = apps.get_model('cashflow', 'Expense')
    Expense.objects.filter(expense_type__in=['materials', 'barber_payment']).update(expense_type='variable')
```

No cambia el esquema de la tabla, así que no necesita bloque de autocuración en `seed.py`. Sí conviene añadir en `seed.py` una reclasificación defensiva idéntica al `forwards` (por si la migración quedó marcada como aplicada sin ejecutarse, como ha pasado antes en Railway).

### 8.3 Puntos de creación que cambian de tipo

| Archivo | Cambio |
| --- | --- |
| `apps/cashflow/views.py:daily_close_view` (~257) | `expense_type=Expense.TYPE_BARBER_PAYMENT` |
| `apps/cashflow/views.py:fix_frank_history_view` (~1341) | `expense_type=Expense.TYPE_BARBER_PAYMENT` |
| `apps/cashflow/management/commands/fix_frank_history.py:65` | `expense_type=Expense.TYPE_BARBER_PAYMENT` |
| `apps/cashflow/services.py:process_checkout` (~993) | `expense_type=Expense.TYPE_MATERIALS` |
| `apps/cashflow/views.py:reject_sale_view` (~1240) | filtro `expense_type__in=['variable','materials']` para seguir borrando el egreso de materiales de ventas viejas y nuevas |

### 8.4 Lectores que pasan de "prefijo" a "tipo" (con el prefijo como respaldo)

- `services.py:is_materials_expense(expense)` → acepta el objeto y devuelve `expense.expense_type == 'materials' or description.startswith(prefijo)`. Ajustar las dos llamadas en `daily_close_detail_view` y `live_cashflow_detail_view`. La prueba `MaterialesEnElCierreTests` se actualiza para pasar el objeto.
- Nuevo helper `services.py:is_frank_daily_expense(expense)` → `expense_type == 'barber_payment' and description.startswith('Pago Diario: Franko')`.
- `apps/roi/services.py`:

```python
total_fixed_expenses      = expense_type='fixed'
total_operational_expenses = expense_type IN ('variable', 'inventory', 'materials')
                             EXCLUYENDO expense_type='barber_payment'
                             EXCLUYENDO description='Pago Diario: Franko'   # respaldo
```

  Un `barber_payment` manual (D5) queda fuera del ROI a propósito: si un superadmin paga un bono a un barbero, no es gasto operativo ni fijo, es costo de personal ya representado en comisiones o decidido aparte. Se documenta en `roi_dashboard.html:413`.

- `apps/roi/models.py`: actualizar `help_text` de `total_operational_expenses` (genera migración `0003` trivial en `roi`).
- `apps/analytics/views.py` (~338–375): `expenses_for_net` excluye `expense_type='barber_payment'` **o** la descripción de Frank. Agregar al `Response` un `expenses_by_type` con los cinco totales del mes.
- `templates/admin/reports.html` (~181–190): tiles "Día a día", "Materiales", "Inventario", "Fijos", "Pago a barberos" a partir de `expenses_by_type`.
- `templates/admin/roi_dashboard.html:413`: texto "Incluye fijos, día a día, materiales e inventario. Excluye pago a barberos (ya está en comisiones)".

### 8.5 Formulario y lista de Egresos

**Permisos** (`add_expense_view`, `edit_expense_view`):

```python
ALLOWED_TYPES_BY_ROLE = {
    'operational_admin': {'variable', 'materials'},
    'superadmin': {'fixed', 'variable', 'inventory', 'materials', 'barber_payment'},
}
```

`admin` (rol estándar) no tiene acceso a esta pantalla hoy (`@operational_admin_required`); no cambia.

**Vista** (`apps/users/views.py:admin_expenses_view`): agregar al contexto `totals_by_type` (dict tipo → monto) y `totals_by_source` para el conjunto filtrado (o para los últimos 50 si no hay filtro, con la etiqueta clara "de los últimos 50 registros").

**Template** (`templates/admin/expenses.html`):

- `<select name="expense_type">` del formulario y `#edit-exp-type` del modal: opciones según rol.
- Badges por tipo (hoy el `else` cae en "Inventario"; con tipos nuevos mostraría mal):
  - `variable` azul "Día a día", `fixed` morado "Fijo", `inventory` esmeralda "Inventario", `materials` ámbar "Materiales", `barber_payment` dorado "Pago barbero".
- Bloque de totales por categoría encima de la tabla.
- Filtro `?expense_type=` y `?payment_source=` en el formulario de filtros.
- El candado de "egreso automático" pasa a depender de `exp.expense_type in ('barber_payment','materials') and (prefijo)`; un `barber_payment` manual de superadmin sí es editable.

### 8.6 Pruebas de la fase 3

- `test_migracion_reclasifica_por_prefijo`: crear egresos con los dos prefijos como `variable`, correr el `forwards` de la migración, verificar tipos.
- `test_cierre_diario_crea_pago_a_frank_como_barber_payment`.
- `test_checkout_crea_materiales_como_materials`.
- `test_roi_no_pierde_materiales_ni_duplica_pago_a_frank`: `total_operational_expenses` incluye `materials` y excluye `barber_payment`.
- `test_operational_admin_no_puede_registrar_barber_payment` (403) y `test_operational_admin_puede_registrar_materials` (200).

---

## 9. Fase 4 — Una sola verdad: Egresos reproduce las Salidas de la caja

### 9.1 Nuevo servicio `compute_outflows`

Archivo: `apps/cashflow/services.py`

```python
def compute_outflows(*, period_start=None, period_end=None, source=None, category=None):
    """Todas las salidas de dinero en una sola lista, con la MISMA acotación que
    compute_cash_box. Es la única función que la caja y la página de Egresos
    usan para listar salidas; si divergen, es un bug aquí."""
```

Cada fila:

| Campo | Valores |
| --- | --- |
| `kind` | `expense` / `advance` / `payment` / `movement` |
| `id` | id del registro origen |
| `at` | `created_at` (para ordenar y acotar) |
| `date` | `Expense.date` o `localdate(created_at)` |
| `label` | descripción, "Vale a X", "Liquidación a X", descripción del movimiento |
| `category` | `fixed` / `variable` / `inventory` / `materials` / `barber_payment` / `advance` / `withdrawal` / `transfer_out` |
| `source` | `cash` / `transfer` (nunca `none` ni `''`: esas no son salidas de caja) |
| `amount` | decimal |
| `registered_by` | nombre |
| `editable` | solo `expense` no automático, según rol |
| `daily_close_id` | si aplica |

Reglas de inclusión (idénticas a `compute_cash_box`):

- `Expense` con `payment_source IN ('cash','transfer')`, sin excluir materiales.
- `BarberPayment` con `expense IS NULL`.
- `BarberAdvance` con `payment_source != ''`.
- `CashMovement` con efecto negativo sobre la caja (`retiro`, `traslado` saliente, `ajuste` negativo), `cash_cut IS NULL` o del corte indicado.

`compute_cash_box_detail.build()` reemplaza su bloque "SALIDAS" por una llamada a `compute_outflows(source=source)`; así la tarjeta de caja y la página de Egresos comparten código.

### 9.2 Página Egresos → "Salidas de dinero"

**Vista** (`apps/users/views.py:admin_expenses_view`):

Parámetros GET:

| Parámetro | Valores | Default |
| --- | --- | --- |
| `period` | `cash` (desde el último corte, usa `cash_period_bounds()`) / `custom` / `recent` | `cash` |
| `date_from`, `date_to` | fechas | vacío |
| `source` | `cash` / `transfer` / vacío | vacío (ambas) |
| `category` | cualquiera de la lista anterior / vacío | vacío |

Contexto: `rows` (de `compute_outflows`), `totals_by_category`, `totals_by_source`, `period_label` ("Desde el corte del 01/09 08:32 hasta ahora"), y `cash_box_out_total` por fuente para mostrar al pie "Coincide con Salidas de la caja: sí/no". Ese "sí/no" es solo un indicador visual; la garantía real es la prueba automática.

Los filtros por `date_from`/`date_to` acotan por `date` (para el usuario es la fecha del egreso); el `period=cash` acota por `at` (igual que la caja). Se muestra cuál de los dos está activo para que H6 deje de confundir.

**Template** (`templates/admin/expenses.html`):

- Título "Salidas de dinero". Filtros: botones "Período de caja actual" / "Últimos 50" / rango; selects de fuente y categoría.
- Tiles de totales por categoría y por fuente.
- Tabla con columna "Tipo" que muestra categoría + `kind` en texto pequeño ("Vale", "Liquidación", "Retiro").
- Acciones por `kind`: `expense` → editar/eliminar como hoy; `advance` → "Anular vale" (`DELETE /api/admin/cashflow/barber-payments/advance/<id>/`); `payment` → "Ver detalle" (abre Caja); `movement` → "Eliminar movimiento" (`DELETE /api/admin/cashflow/cash/movements/<id>/`, solo superadmin).
- El formulario "Registrar nuevo egreso" no cambia de lugar; solo recibe el aviso de D2.

**Rendimiento**: el período de caja tiene hoy ~90 salidas y ~180 entradas; `compute_outflows` hace 4 consultas con `select_related`. Sin paginación en esta fase.

### 9.3 Prueba de igualdad

`apps/cashflow/tests.py::ConciliacionTests`:

- Fixture con uno de cada: gasto normal en efectivo, gasto en transferencia, materiales en efectivo, materiales `none`, Pago Diario de Frank (Expense + BarberPayment enlazado), vale con fuente, vale histórico sin fuente, liquidación no-Frank por transferencia, retiro en efectivo, traslado efectivo→transferencia, inyección.
- `test_salidas_de_egresos_igualan_salidas_de_la_caja`: para `source` en (`cash`, `transfer`), `sum(compute_outflows(source))` == `compute_cash_box()[f'{source}_out']`.
- `test_la_pagina_de_egresos_muestra_el_mismo_total`: GET `/admin-panel/expenses/?period=cash&source=cash` y comparar el total renderizado.
- `test_tras_un_corte_el_periodo_arranca_en_el_corte`.

---

## 10. Fase 5 — Cierre con el dueño

1. Con las fases 2 a 4 en producción, los socios cuentan el efectivo físico y lo comparan con el "Debe haber".
2. Si hay diferencia heredada, se usa "Ajustar saldo" (`POST /api/admin/cashflow/cash/starting-point/` o el botón "Fijar punto de partida") con nota del motivo. Desde ahí el número es auditable.
3. Regla de operación acordada con Frank y los socios:
   - Adelantos: solo "Dar vale". Nunca como egreso.
   - Liquidaciones: siempre indicar efectivo o transferencia.
   - Materiales: se indica la fuente al confirmar la venta.
   - Egresos libres: solo compras del negocio, con foto de soporte cuando la haya.
4. Se entrega al dueño una guía de una página (sección nueva en `ADMIN_GUIDE.md`) con esas reglas y con la lectura de la nueva página "Salidas de dinero".

---

## 11. Orden de despliegue, riesgos y reversión

| Paso | Qué sube | Antes de subir | Cómo se revierte |
| --- | --- | --- | --- |
| 1 | Fase 1 (solo comando) | nada | no aplica |
| 2 | Fase 2 | Confirmar D1 con el dueño; comunicar que el "Debe haber" de efectivo bajará en el total de materiales del período | `git revert`; la migración 0016 es solo `choices`, reversible sin pérdida |
| 3 | Reparación D3 (comando por id) | Lista aprobada | Cada conversión queda en el log de auditoría; se puede recrear el `Expense` a mano |
| 4 | Fase 3 | nada | `git revert` del commit completo (código + migración + bloque de `seed.py`) y después `migrate cashflow 0016`. **En ese orden**: `seed.py` corre en cada arranque justo después de `migrate` y repite la reclasificación, así que revertir solo la migración no sirve de nada mientras el código siga desplegado. |
| 5 | Fase 4 | nada | `git revert`; no hay migración |
| 6 | Fase 5 | Fases anteriores estables al menos una jornada completa con cierre | no aplica |

Verificaciones **antes** de desplegar, contra producción:

```bash
# 1. El historial de migraciones está al día (0015 y roi/0002 registradas).
python manage.py showmigrations cashflow roi

# 2. La auditoría, para saber cuánto va a bajar el "Debe haber".
python manage.py audit_cash_box --limit 50

# 3. Ningún pago de cierre quedó sin enlace a su egreso (sección 6b del reporte).
#    Si aparece alguno, seed.py lo re-enlaza en el arranque siguiente.
```

Riesgos conocidos:

- **Migraciones en Railway**: el historial ha sido poco confiable. Las dos migraciones de este plan no alteran columnas, y la reclasificación se repite en `seed.py` de forma idempotente, dentro de un `try/except` para que un fallo ahí no impida el arranque.
- **Migración a medias**: si 0016 se aplica y 0017 no, la app arranca igual pero el ROI cuenta dos veces el pago a Frank. El bloque defensivo de `seed.py` lo corrige en el mismo arranque.
- **Cambio del "Debe haber"** en la fase 2: es el efecto buscado, pero si el dueño no está avisado parecerá otro error. Se comunica con la cifra exacta de la fase 1.
- **Un tipo nuevo que no esté en las listas del ROI desaparece del ROI**. Cubierto por `test_roi_no_pierde_materiales_ni_duplica_pago_a_frank`.
- **Egresos `none`** podrían usarse para esconder salidas. Por eso solo superadmin puede elegirlo a mano; el checkout sí lo permite a Frank porque el monto igual se descuenta de su base de comisión.

---

## 12. Checklist de ejecución

- [x] F1 · `audit_cash_box` escrito y probado contra un escenario sintético
- [ ] F1 · Corrido en **producción**; salida guardada y enviada al dueño
- [ ] F1 · D1 confirmada por el dueño; lista D3 aprobada
- [x] F2 · `Expense.payment_source` admite `none` (migración 0016)
- [x] F2 · `compute_cash_box` / `compute_cash_box_detail` incluyen materiales por fuente
- [x] F2 · Checkout pide fuente de materiales; textos de `manual_service.html` y `bookings.html` corregidos
- [x] F2 · `add_expense_view` / `edit_expense_view` rechazan descripciones tipo vale
- [x] F2 · `pay_barber_view` exige `payment_source`; modal de liquidación con selector
- [x] F2 · Pruebas en verde (37 en total: las 10 originales + 27 nuevas)
- [ ] F2 · Desplegado y comunicado al dueño
- [ ] D3 · `convert_expense_to_advance` corrido con la lista aprobada
- [x] F3 · Tipos `materials` y `barber_payment` + migración 0017 con backfill
- [x] F3 · Puntos de creación actualizados (sección 8.3)
- [x] F3 · ROI y analytics por tipo, con el desglose `expenses_by_type`
- [x] F3 · El reporte mensual muestra "En qué se fue la plata" por categoría
- [x] F3 · Textos del panel ROI acordes a la regla nueva
- [x] F3 · Formulario, badges, totales y permisos en Egresos
- [x] F3 · Reclasificación defensiva en `seed.py`, dentro de `try/except`
- [x] F4 · `compute_outflows` y `compute_cash_box_detail` comparten código
- [x] F4 · Página "Salidas de dinero" con filtros por período de caja, fuente y categoría
- [x] F4 · Prueba de igualdad caja ↔ página en verde
- [x] Extra · Doble criterio para el pago de Frank y guard contra borrar su egreso
- [x] Extra · Revisión adversarial del diff; ocho defectos corregidos y cubiertos con pruebas
- [x] F5 · Reglas de uso escritas en `GUIA_CAJA.md`, enlazada desde `ADMIN_GUIDE.md`
- [ ] F5 · Conteo físico con los socios y punto de partida si aplica

---

## 13. Glosario

- **Período de caja**: desde el último `CashCut.closed_at` hasta ahora. Es lo que usa el "Debe haber".
- **Debe haber**: `apertura + entradas − salidas` por fuente. Cuánto debería haber físicamente.
- **Fuente**: de qué caja salió o a qué caja entró la plata: efectivo o transferencia.
- **Vale / adelanto**: `BarberAdvance`. Plata entregada a un barbero a cuenta de sus comisiones. Sale de la caja y baja su saldo.
- **Liquidación**: `BarberPayment` con `daily_close=None`. Pago del neto (acumulado − vales) a un barbero distinto de Frank.
- **Pago Diario: Franko**: `Expense` + `BarberPayment` enlazados que crea el cierre diario. La caja cuenta el `Expense` y omite el `BarberPayment` para no duplicar.
- **Materiales de servicio**: `Expense` que crea el checkout cuando Frank separa el costo de insumos de un servicio manual. Reduce la base de comisión y, desde la fase 2, resta de la caja según su fuente.
- **Ledger de Frank**: `Σ ganado − Σ vales − Σ pagos`, siempre derivado, nunca almacenado (`compute_frank_ledger`).

---

## 14. Lo que quedó implementado (16 sep 2026)

### Archivos nuevos

| Archivo | Qué hace |
| --- | --- |
| `apps/cashflow/management/commands/audit_cash_box.py` | Auditoría de solo lectura. Nueve secciones: período, caja actual, materiales excluidos, egresos que parecen vale, liquidaciones y su fuente, vales del sistema, pagos de cierre sin enlace, movimientos manuales, fechas desalineadas, y la caja corregida. `--all`, `--json`, `--limit`. |
| `apps/cashflow/management/commands/convert_expense_to_advance.py` | Convierte un egreso mal registrado en `BarberAdvance`, conservando monto, fuente y fecha de registro. Simula sin `--apply`. |
| `apps/cashflow/migrations/0016_expense_payment_source_none.py` | `payment_source` admite `none`. |
| `apps/cashflow/migrations/0017_expense_types_materials_barber_payment.py` | Tipos `materials` y `barber_payment` + backfill idempotente por prefijo. |
| `apps/roi/migrations/0003_snapshot_help_text_materiales.py` | Solo `help_text`. |

### Funciones nuevas en `apps/cashflow/services.py`

- `compute_outflows(...)` — la lista única de salidas. De ella cuelgan la tarjeta de caja y la pantalla de Egresos.
- `summarize_outflows(rows)` — totales por fuente y por categoría.
- `looks_like_advance(descripcion)` — detecta adelantos escritos como egreso.
- `is_frank_daily_expense(egreso)` — identifica el pago automático a Frank.
- `is_materials_expense(egreso)` — ahora acepta el objeto y decide por tipo, con el prefijo como respaldo. La firma vieja (solo texto) sigue funcionando.
- `allowed_expense_types(rol)` / `EXPENSE_TYPES_BY_ROLE` — qué tipo puede registrar cada rol.
- `OUTFLOW_CATEGORIES` — las diez categorías de salida.

### Pruebas

`apps/cashflow/tests.py` pasa de 10 a 37 pruebas. Las clases nuevas:

- **`ConciliacionCajaTests`** — el invariante (las salidas listadas igualan las de la caja, en las dos cajas y en el detalle), el corte que arranca el período de cero, las tres fugas cerradas, y los dos riesgos que encontró la revisión.
- **`CategoriasDeEgresoTests`** — detección por tipo y por prefijo, el ROI que cuenta materiales y no duplica el pago a Frank, el bono que sí pesa en el ROI, los permisos por rol, y el backfill de la migración.
- **`RegresionesDeLaRevisionTests`** — una prueba por cada defecto que encontró la revisión del propio cambio.

### Ocho correcciones que salieron de revisar el propio cambio

Antes de dar el trabajo por terminado se hizo una revisión adversarial del diff:
varios revisores independientes buscaron defectos y otros intentaron refutar cada
hallazgo. Sobrevivieron ocho, todos reales. Los seis primeros eran defectos que
introdujo esta misma implementación.

| # | Qué estaba mal | Consecuencia |
| --- | --- | --- |
| A | `compute_outflows` filtraba los movimientos por corte **siempre**, no solo dentro del período de caja | Un retiro dejaba de existir apenas se cerraba un corte: buscar "esta semana" mostraba los egresos pero ningún retiro. En el escenario de prueba, $900.000 reportados donde salieron $1.900.000 |
| B | El total de "Últimas 50" se calculaba sobre el histórico entero | La pantalla decía un total encima de una tabla cuyas filas sumaban otra cosa |
| C | Borrar un cierre eliminaba **cualquier** egreso de tipo `barber_payment` | Un bono registrado a mano que cayera en ese cierre se borraba sin dejar rastro, y nadie lo recrea al recerrar |
| D | El candado de "egreso del sistema" miraba el tipo, no la descripción | Un egreso de materiales registrado a mano quedaba sin botón de editar |
| E | `edit_expense_view` validaba la descripción aunque no hubiera cambiado | Los egresos que ya traían la palabra "vale" quedaban congelados, que es justo lo contrario de lo que hace falta para arreglarlos |
| F | La pantalla del barbero (`/barbero/pagos-vales/`) no mandaba la fuente al liquidar | Quedó rota al exigirla el endpoint |
| G | El comando `fix_frank_history` seguía creando el pago de Frank como `variable` | Solo se había actualizado la vista, no el comando |
| H | El `help_text` del ROI contradecía el cálculo real tras la corrección D5b | Documentación engañosa |

Además, el comando de auditoría había quedado **desfasado**: se escribió cuando la
caja excluía los materiales y su sección final los sumaba a mano. Después de la
fase 2 eso los descontaba por segunda vez, y le habría reportado al dueño una
caída del "Debe haber" que no existe. Ahora esa sección verifica que estén
incluidos en vez de corregir nada.

Las seis regresiones tienen su propia prueba en `RegresionesDeLaRevisionTests`.
Dos de ellas se comprobaron revirtiendo el arreglo a propósito para confirmar que
la prueba falla.

### Dos correcciones que salieron del mapeo previo

1. **Un pago a barbero registrado a mano desaparecía del ROI.** La exclusión era por categoría, pero "ya está en comisiones" solo es cierto para el pago automático de Frank. Un bono de $100.000 habría quedado fuera del neto y los socios se habrían repartido utilidad inexistente. Ahora se excluye ese egreso concreto, con su descripción protegida como patrón reservado.

2. **El no-doble-conteo del pago de Frank colgaba de un solo campo.** `BarberPayment.expense` es `SET_NULL`: si se borraba el egreso, el pago quedaba huérfano y la caja lo empezaba a restar aparte. Ahora hay un segundo criterio (`daily_close__isnull=True`), un guard que impide borrar ese egreso suelto, y `seed.py` re-enlaza en cada arranque los pagos que quedaron sin enlace.

### Qué ve el dueño

- **Caja** — el "Debe haber" ahora resta los materiales que salieron del cajón. El desplegable de Salidas nombra cada categoría.
- **Egresos** — la pantalla se llama **Salidas de Dinero** y lista todo: egresos, vales, liquidaciones, retiros y traslados. Filtros por período de caja, efectivo o transferencia, y categoría. Arriba, el total y el desglose de en qué se fue la plata. Al pie, una línea que dice si cuadra con el control de caja.
- **Liquidar a un barbero** — ahora pregunta si se paga en efectivo o por transferencia.
- **Confirmar un servicio con materiales** — ahora pregunta de qué caja salió el insumo, o si no salió de caja.
- **Registrar un egreso tipo "Vale Franko"** — se rechaza con un enlace a "Dar vale" en Caja.
