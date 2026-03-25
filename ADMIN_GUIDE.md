# 🔐 Panel Administrativo - Área 30 Barber Club

## Acceso al Panel Admin

### 📍 Ubicación del Botón
- **Ubicación:** Pie de página (footer) de todas las páginas
- **Aspecto:** Ícono discreto (⚙) en gris muy tenue
- **Ubicación exacta:** Junto al copyright "© 2026 Área 30 Barber Club"

### 🔑 Credenciales de Inicio de Sesión
```
Usuario: admin
Contraseña: admin123
```

**Nota:** Puedes cambiar estas credenciales a través de variables de entorno:
```bash
export ADMIN_USERNAME="tu_usuario"
export ADMIN_PASSWORD="tu_contraseña"
```

---

## 📊 Panel de Control - Funcionalidades

### 1. **Estadísticas Principales** (Superior)
Muestra 4 métricas clave en tiempo real:
- **Total Ingresos:** Suma de todos los servicios completados en COP
- **Total Cortes:** Número de servicios completados
- **Promedio x Corte:** Ingreso promedio por servicio completado
- **Reservas Pendientes:** Citas que aún no se confirman

### 2. **Gráficas Interactivas**
#### 📈 Ingresos por Mes
- Gráfica de línea que muestra los ingresos mensuales
- Solo cuenta servicios marcados como "completados"
- Útil para analizar tendencias de negocio

#### 🍩 Servicios Más Solicitados
- Gráfica tipo dónut (pastel)
- Muestra qué servicios son los más populares
- Código de colores par fácil identificación

### 3. **📅 Calendario de Reservas**
- Vista interactiva de todas las reservas
- Puedes cambiar entre vista mensual y semanal
- Haz clic en una cita para ver detalles
- Todas las reservas se muestran (pendientes, completadas, canceladas)

### 4. **📋 Tabla de Reservas Completa**
Muestra todas las citas con:
- **Cliente:** Nombre y número de teléfono
- **Servicio:** Tipo de corte o servicio
- **Fecha y Hora:** Cuándo está programada
- **Precio:** Valor del servicio en COP
- **Estado:** Pendiente / Completado / Cancelado

#### Estados de Reserva
- 🟡 **Pendiente:** Cita programada pero sin confirmar
- 🟢 **Completado:** Servicio ya realizado
- 🔴 **Cancelado:** Cita cancelada

### 5. **⚙️ Acciones en Reservas**
Dos botones principales por cada reserva:
- ✓ **Completar:** Marca la cita como completada y envía email de confirmación
- ✗ **Cancelar:** Cancela la cita

---

## 🔒 Seguridad

- El panel está protegido por sesión segura
- Solo accesible después de login correcto
- Botón de logout en la esquina superior derecha
- La sesión se mantiene activa durante tu navegación

---

## 📍 URLs del Sistema

### Públicas
- `http://127.0.0.1:5000/` - Página de inicio
- `http://127.0.0.1:5000/services` - Servicios
- `http://127.0.0.1:5000/gallery` - Galería
- `http://127.0.0.1:5000/booking` - Reservar cita

### Administrativas (Requieren login)
- `http://127.0.0.1:5000/admin/login` - Página de login
- `http://127.0.0.1:5000/admin` - Panel principal
- `http://127.0.0.1:5000/admin/logout` - Cerrar sesión

### APIs
- `GET /api/admin/stats` - Obtener estadísticas en JSON (requiere login)
- `POST /admin/bookings/<id>/complete` - Marcar como completado
- `POST /admin/bookings/<id>/cancel` - Cancelar cita

---

## 💡 Tips de Uso

1. **Filtro por Estado:** En la tabla, el color del estado te ayuda a identificar rápidamente el estado
2. **Verificar Tendencias:** Usa la gráfica de ingresos para ver en qué meses venden más
3. **Monitorear Servicios:** La gráfica de servicios te muestra qué cortes son más solicitados
4. **Confirmar Citas:** Usa el calendario para ver todas las citas del mes de un vistazo
5. **Email Automático:** Al marcar como completado, se envía email al cliente automáticamente

---

## 🚀 Próximas Mejoras Posibles

- [ ] Exportar reportes en PDF
- [ ] Filtrar reservas por fecha o estado
- [ ] Agregar notas personalizadas a citas
- [ ] Sistema de descuentos
- [ ] Historial de cambios
- [ ] Notificaciones en tiempo real

---

**Panel Administrativo v1.0 | Área 30 Barber Club | 2026**
