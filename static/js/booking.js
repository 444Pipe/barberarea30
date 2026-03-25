// Configuración de servicios manejados en el frontend
const SERVICE_OPTIONS = {
  'Corte Imperial': { slug: 'corte-basico', price: 30000 },
  'Club Experience': { slug: 'asesoria-visajista', price: 60000 },
  'Ritual de Barba': { slug: 'corte-barba', price: 25000 }
};

// Establecer fecha mínima (hoy), preparar labels de horas y
// preseleccionar servicio si viene en la URL
document.addEventListener('DOMContentLoaded', () => {
  const todayStr = new Date().toISOString().split('T')[0];
  document.querySelectorAll('input[type="date"]').forEach(input => {
    input.setAttribute('min', todayStr);
  });

  // Guardar label original de cada opción de hora para poder añadir "(Ocupado)"
  const timeSelect = document.querySelector('select[name="time"]');
  if (timeSelect) {
    timeSelect.querySelectorAll('option').forEach(opt => {
      if (!opt.dataset.label) {
        opt.dataset.label = opt.textContent;
      }
    });
  }

  const params = new URLSearchParams(window.location.search);
  const serviceParam = params.get('service');
  if (serviceParam) {
    const serviceSelect = document.querySelector('select[name="service"]');
    if (serviceSelect) {
      serviceSelect.value = serviceParam;
    }
  }

  // Actualizar disponibilidad de horas cuando cambie la fecha
  const dateInput = document.querySelector('input[name="date"]');
  if (dateInput && timeSelect) {
    dateInput.addEventListener('change', () => {
      const value = dateInput.value;
      if (value) {
        updateTimeAvailability(value, timeSelect);
      }
    });
  }
});

async function updateTimeAvailability(date, timeSelect) {
  try {
    const res = await fetch(`/api/availability?date=${encodeURIComponent(date)}`);
    if (!res.ok) return;
    const data = await res.json();
    if (!data.ok) return;

    const taken = data.taken_times || [];

    let availableCount = 0;
    timeSelect.querySelectorAll('option').forEach(opt => {
      if (!opt.value) return; // opción vacía

      const baseLabel = opt.dataset.label || opt.textContent;
      const isTaken = taken.includes(opt.value);
      opt.disabled = isTaken;
      opt.textContent = isTaken ? `${baseLabel} (Ocupado)` : baseLabel;
      if (!isTaken) availableCount += 1;
    });

    // Si no hay horarios disponibles, mostrar mensaje en la primera opción
    const placeholder = timeSelect.querySelector('option[value=""]');
    if (placeholder) {
      placeholder.textContent = availableCount > 0
        ? 'Selecciona una hora'
        : 'No hay horarios disponibles en esta fecha';
    }

    // Resetear selección si la hora actual quedó ocupada
    if (timeSelect.value && taken.includes(timeSelect.value)) {
      timeSelect.value = '';
    }
  } catch (err) {
    console.error('Error obteniendo disponibilidad:', err);
  }
}

document.getElementById('booking-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const formData = new FormData(e.target);
  const name = formData.get('name')?.trim();
  const phone = formData.get('phone')?.trim();
  const email = formData.get('email')?.trim();
  const service = formData.get('service');
  const date = formData.get('date');
  const time = formData.get('time');
  const notes = formData.get('notes')?.trim();

  // Validar campos obligatorios
  if (!name || !phone || !email || !service || !date || !time) {
    showErrorMessage('Por favor completa todos los campos requeridos (Nombre, Celular, Email, Servicio, Fecha y Hora)');
    return;
  }

  // Validar formato de email
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailRegex.test(email)) {
    showErrorMessage('Por favor ingresa un email válido');
    return;
  }

   // Validar que la fecha no sea anterior a hoy
  const todayStr = new Date().toISOString().split('T')[0];
  if (date < todayStr) {
    showErrorMessage('La fecha debe ser hoy o una fecha futura');
    return;
  }

  const serviceInfo = SERVICE_OPTIONS[service];
  if (!serviceInfo) {
    showErrorMessage('Servicio seleccionado no es válido');
    return;
  }

  const data = {
    name,
    phone,
    email,
    service_slug: serviceInfo.slug,
    service,
    price_num: serviceInfo.price,
    date,
    time,
    notes
  };

  try {
    const response = await fetch('/api/bookings', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(data)
    });

    if (response.ok) {
      localStorage.setItem('lastBooking', JSON.stringify(data));
      showSuccessMessage();
    } else {
      showErrorMessage('Error al guardar la reserva. Intenta de nuevo.');
    }
  } catch (error) {
    console.error('Error al crear reserva:', error);
    showErrorMessage('Ocurrió un error al enviar la reserva.');
  }
});

function showSuccessMessage() {
  const form = document.getElementById('booking-form');
  const message = document.createElement('div');
  message.className = 'fixed top-4 right-4 bg-green-500 text-white px-6 py-4 rounded-lg shadow-lg z-50 animate-pulse';
  message.textContent = '✓ ¡Solicitud recibida! Te contactaremos pronto por WhatsApp';
  document.body.appendChild(message);
  form.reset();
  setTimeout(() => message.remove(), 5000);
}

function showErrorMessage(customMessage) {
  const message = document.createElement('div');
  message.className = 'fixed top-4 right-4 bg-red-500 text-white px-6 py-4 rounded-lg shadow-lg z-50';
  message.textContent = customMessage || '✗ Error al enviar. Por favor intenta de nuevo.';
  document.body.appendChild(message);
  setTimeout(() => message.remove(), 5000);
}
