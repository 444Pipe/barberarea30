// ─── Booking Page JS ─────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  // Preseleccionar servicio desde URL
  const params = new URLSearchParams(window.location.search);
  const serviceParam = params.get('service');
  if (serviceParam) {
    const serviceSelect = document.querySelector('select[name="service"]');
    if (serviceSelect) serviceSelect.value = serviceParam;
  }

  // Escuchar cambios en barbero y fecha para recargar horarios
  const barberSelect = document.getElementById('barber-select');
  const dateInput    = document.getElementById('selected-date-input');

  if (barberSelect) barberSelect.addEventListener('change', tryLoadSlots);
  if (dateInput)    dateInput.addEventListener('change', tryLoadSlots);
});

function tryLoadSlots() {
  const barberId = document.getElementById('barber-select')?.value;
  const date     = document.getElementById('selected-date-input')?.value;
  if (barberId && date) {
    loadAvailableSlots(barberId, date);
  }
}

// Etiquetas bonitas para cada hora
const HOUR_LABELS = {
  '09:00': '09:00 AM', '10:00': '10:00 AM', '11:00': '11:00 AM',
  '12:00': '12:00 PM', '13:00': '01:00 PM', '14:00': '02:00 PM',
  '15:00': '03:00 PM', '16:00': '04:00 PM', '17:00': '05:00 PM',
  '18:00': '06:00 PM', '19:00': '07:00 PM', '20:00': '08:00 PM',
};

async function loadAvailableSlots(barberId, date) {
  const timeSelect = document.getElementById('time-select');
  const hint       = document.getElementById('time-hint');
  if (!timeSelect) return;

  timeSelect.innerHTML = '<option value="">Cargando horarios...</option>';
  timeSelect.disabled = true;

  try {
    const res  = await fetch(`/api/barbers/${barberId}/availability/?date=${date}`);
    const data = await res.json();

    if (data.day_off) {
      timeSelect.innerHTML = '<option value="">Sin horario este día</option>';
      if (hint) hint.classList.add('hidden');
      return;
    }

    const slots = data.slots || [];
    if (!slots.length) {
      timeSelect.innerHTML = '<option value="">No hay horarios disponibles</option>';
      if (hint) hint.classList.add('hidden');
      return;
    }

    let html = '<option value="" class="bg-jet">Selecciona una hora</option>';
    let hasAvailable = false;
    slots.forEach(slot => {
      const label = HOUR_LABELS[slot.time] || slot.time;
      if (slot.available) {
        html += `<option value="${slot.time}" class="bg-jet">${label}</option>`;
        hasAvailable = true;
      } else {
        html += `<option value="${slot.time}" disabled class="bg-jet text-smoke/30">${label} — No disponible</option>`;
      }
    });

    timeSelect.innerHTML = html;
    if (hint) hint.classList.toggle('hidden', !slots.some(s => !s.available));

    if (!hasAvailable) {
      timeSelect.innerHTML = '<option value="">Sin horarios libres este día</option>';
    }
  } catch (err) {
    console.error('Error cargando slots:', err);
    timeSelect.innerHTML = '<option value="">Error al cargar horarios</option>';
  } finally {
    timeSelect.disabled = false;
  }
}

// ─── Envío del formulario ────────────────────────────────

document.getElementById('booking-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const submitBtn = e.target.querySelector('button[type="submit"]');
  const originalBtnText = submitBtn ? submitBtn.textContent : '';

  const formData = new FormData(e.target);
  const name    = formData.get('name')?.trim();
  const phone   = formData.get('phone')?.trim();
  const email   = formData.get('email')?.trim();
  const service = formData.get('service');
  const barber  = formData.get('barber');
  const date    = formData.get('date');
  const time    = formData.get('time');

  if (!name || !phone || !email || !service || !date || !time) {
    showErrorMessage('Por favor completa todos los campos requeridos (Nombre, Celular, Email, Servicio, Fecha y Hora)');
    return;
  }

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailRegex.test(email)) {
    showErrorMessage('Por favor ingresa un email válido');
    return;
  }

  // ── Nivel 3: Deshabilitar botón para evitar múltiples envíos ─────────────
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Procesando...';
  }
  // ─────────────────────────────────────────────────────────────────────────

  // Obtener service_id y price del select de servicios
  const serviceSelect = document.getElementById('service-select');
  const selectedOption = serviceSelect?.options[serviceSelect.selectedIndex];
  const serviceId    = selectedOption?.dataset.serviceId || selectedOption?.value;
  const servicePrice = selectedOption?.dataset.price || 0;

  const payload = {
    client_name:      name,
    client_phone:     phone,
    client_email:     email,
    service_id:       serviceId,
    barber_id:        barber || 'any',
    date,
    time,
    price:            servicePrice,
    privacy_accepted: 'true',
  };

  try {
    const response = await fetch('/api/bookings/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const result = await response.json();

    if (response.ok && result.ok) {
      showSuccessMessage();
      e.target.reset();
      document.getElementById('time-select').innerHTML = '<option value="">Selecciona barbero y fecha primero</option>';
      // Mantener el botón deshabilitado tras éxito para evitar re-envío
      if (submitBtn) submitBtn.textContent = '✓ Reserva enviada';
    } else {
      const errMsg = result.error || result.errors || 'Error al guardar la reserva. Intenta de nuevo.';
      showErrorMessage(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg));
      // Re-habilitar el botón solo en caso de error para que el usuario corrija y reintente
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = originalBtnText;
      }
    }
  } catch (error) {
    console.error('Error al crear reserva:', error);
    showErrorMessage('Ocurrió un error al enviar la reserva.');
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = originalBtnText;
    }
  }
});

function showSuccessMessage() {
  const message = document.createElement('div');
  message.className = 'fixed top-4 right-4 bg-emerald-600 text-white px-6 py-4 rounded-lg shadow-lg z-50';
  message.textContent = '✓ ¡Solicitud recibida! Te contactaremos pronto por WhatsApp';
  document.body.appendChild(message);
  setTimeout(() => message.remove(), 6000);
}

function showErrorMessage(customMessage) {
  const message = document.createElement('div');
  message.className = 'fixed top-4 right-4 bg-red-600 text-white px-6 py-4 rounded-lg shadow-lg z-50 max-w-sm';
  message.textContent = customMessage || '✗ Error al enviar. Por favor intenta de nuevo.';
  document.body.appendChild(message);
  setTimeout(() => message.remove(), 6000);
}


