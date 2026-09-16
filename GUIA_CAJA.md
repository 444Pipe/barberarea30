# Cómo se maneja la plata en el sistema

Guía para Camilo, Juan David y Frank.
Escrita el 16 de septiembre de 2026, después del arreglo de la caja.

---

## La idea en una frase

El sistema tiene **una sola caja**, y ahora hay **una sola pantalla** donde se ve todo lo que salió de ella: **Salidas de Dinero**. Si el número de esa pantalla y el "Debe haber" de Caja no coinciden, es un error del sistema y hay que avisar. Antes no coincidían nunca, porque cada pantalla contaba cosas distintas.

---

## Las cuatro formas en que sale plata

Cada una tiene su botón. Usar el botón equivocado es lo que causaba los descuadres.

### 1. Un gasto del negocio → botón "Registrar Egreso"

Desinfectante, boletas, arriendo, una compra de inventario. Se indica de qué caja salió: efectivo o transferencia.

Categorías, para poder ver en qué se va la plata:

| Categoría | Para qué |
| --- | --- |
| **Día a día** | Lo corriente: aseo, compras menores, mantenimiento |
| **Fijo** | Arriendo, servicios públicos, nómina. Solo los socios |
| **Compra de inventario** | Producto para vender o para usar. Solo los socios |
| **Materiales de servicio** | Insumos de un servicio concreto: tinte, color |
| **Pago a barberos** | Un bono o un pago fuera de la liquidación normal. Solo los socios |

### 2. Un adelanto a un barbero → botón "Dar vale", en Caja

**Nunca como egreso.** El sistema ahora rechaza un egreso que se llame "Vale Franko" o parecido, y ofrece el enlace al botón correcto.

La razón: el vale hace dos cosas a la vez. Saca la plata de la caja **y** se la descuenta al barbero de lo que se le debe. Escrito como egreso solo hacía lo primero, así que al cerrar el día el sistema seguía sugiriendo pagarle completo, y esa plata se entregaba dos veces.

### 3. Pagarle a un barbero lo que se le debe → botón "Liquidar"

Ahora pregunta **si se le paga en efectivo o por transferencia**. Antes siempre lo guardaba como efectivo, así que un pago hecho por transferencia dejaba el efectivo descuadrado.

El monto que muestra ya tiene descontados los vales del período.

### 4. Sacar plata de la caja sin que sea un gasto → botones de Caja

"Retirar" cuando un socio saca utilidades. "Trasladar" cuando se consigna efectivo a la cuenta. "Inyectar dinero" cuando se pone plata. "Ajustar saldo" cuando el conteo físico no cuadra y se quiere fijar el número real.

---

## El pago diario a Frank

Lo genera el cierre del día. No se registra a mano y no se puede borrar desde la pantalla de Salidas: para revertirlo hay que eliminar el cierre, que deshace todo junto.

---

## Los materiales de un servicio

Al confirmar un servicio con materiales separados, el sistema pregunta **de dónde salió la plata de esos insumos**:

- **Efectivo de la caja** o **Transferencia** cuando se compraron o se le reembolsaron a alguien. Descuenta de esa caja.
- **No salió de caja** cuando el barbero puso el insumo de su bolsillo, o ya estaba comprado. Se registra el costo igual, porque baja la base de comisión, pero no toca el saldo.

Antes el sistema decía en pantalla que los materiales se descontaban de la caja, pero no los descontaba. Por eso al contar el cajón siempre faltaba plata.

---

## La pantalla de Salidas de Dinero

Reemplaza la de Egresos. Ahora lista **todo**: egresos, vales, liquidaciones, retiros y traslados.

Arriba tiene:

- El total que salió, y cuánto de eso fue en efectivo y cuánto por transferencia.
- **En qué se fue**: el desglose por categoría. Ahí se ve cuánto en materiales, cuánto en el día a día y cuánto en pago a barberos.
- Al pie, una línea que dice si **cuadra con el control de caja**. Si dice que no cuadra, avisar.

Los filtros de arriba:

- **Período de caja** (el que viene por defecto). Desde el último corte hasta hoy. Es el mismo período que usa el "Debe haber", y por eso los dos números coinciden.
- **Últimas 50**. Un vistazo rápido a lo más reciente.
- **Hoy / Ayer / Esta semana / Este mes**, o un rango de fechas.
- **Salió de**: efectivo o transferencia.
- **Categoría**.

---

## Cómo cuadrar la caja

1. Contar el efectivo físico del cajón.
2. Abrir **Caja** y mirar el "Debe haber" de Efectivo.
3. Si coinciden, todo bien.
4. Si no coinciden, abrir **Salidas de Dinero** con el filtro "Período de caja" y buscar qué falta o qué sobra. Ahí está cada peso que salió.
5. Si queda una diferencia que viene de antes y no se puede explicar, usar **Ajustar saldo** con una nota del motivo. De ahí en adelante el número vuelve a ser confiable.

---

## Las reglas, en corto

- Un adelanto se da con **Dar vale**. Nunca como egreso.
- Al liquidar, siempre indicar **efectivo o transferencia**.
- Al confirmar un servicio con materiales, indicar **de qué caja salieron**.
- Un egreso es para compras del negocio. Con foto de soporte cuando se pueda.
- El pago diario a Frank y los materiales los pone el sistema solo. No tocarlos a mano.
