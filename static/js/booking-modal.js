// Configuración de servicios manejados en el frontend (mismo mapa que booking.js)
const MODAL_SERVICE_OPTIONS = {
  'Corte Imperial': { slug: 'corte-basico', price: 30000 },
  'Club Experience': { slug: 'asesoria-visajista', price: 60000 },
  'Ritual de Barba': { slug: 'corte-barba', price: 25000 }
};

// Gestionar modal de reserva
function openBookingModal() {
  const modal = document.getElementById('booking-modal');
  if (modal) {
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
  }
}

function closeBookingModal() {
  const modal = document.getElementById('booking-modal');
  if (modal) {
    modal.classList.remove('active');
    document.body.style.overflow = 'auto';
  }
}

// Event listeners para abrir modal
document.querySelectorAll('[data-open-booking]').forEach(btn => {
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    openBookingModal();
  });
});

// Configuración al cargar el documento: cerrar modal con click en fondo
// y establecer fecha mínima (hoy) en todos los inputs de fecha
document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('booking-modal');
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        closeBookingModal();
      }
    });

    // Botón cerrar
    const closeBtn = modal.querySelector('[data-close-modal]');
    if (closeBtn) {
      closeBtn.addEventListener('click', closeBookingModal);
    }
  }

  // Establecer fecha mínima (hoy) para cualquier input de fecha
  const todayStr = new Date().toISOString().split('T')[0];
  document.querySelectorAll('input[type="date"]').forEach(input => {
    input.setAttribute('min', todayStr);
  });

  // Preparar labels y listeners para disponibilidad de horas en el modal
  const timeSelect = document.querySelector('#booking-form-modal select[name="time"]');
  const dateInput = document.querySelector('#booking-form-modal input[name="date"]');

  if (timeSelect) {
    timeSelect.querySelectorAll('option').forEach(opt => {
      if (!opt.dataset.label) {
        opt.dataset.label = opt.textContent;
      }
    });
  }

  if (dateInput && timeSelect) {
    dateInput.addEventListener('change', () => {
      const value = dateInput.value;
      if (value) {
        updateModalTimeAvailability(value, timeSelect);
      }
    });
  }

  // Formulario de reserva en modal
  const form = document.getElementById('booking-form-modal');
  if (form) {
    form.addEventListener('submit', async (e) => {
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
        showErrorMessage('Por favor completa todos los campos requeridos');
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

      const serviceInfo = MODAL_SERVICE_OPTIONS[service];
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
          form.reset();
          setTimeout(() => closeBookingModal(), 2000);
        } else {
          showErrorMessage('Error al guardar la reserva. Intenta de nuevo.');
        }
      } catch (error) {
        console.error('Error al crear reserva (modal):', error);
        showErrorMessage('Ocurrió un error al enviar la reserva.');
      }
    });
  }
});

async function updateModalTimeAvailability(date, timeSelect) {
  try {
    const res = await fetch(`/api/availability?date=${encodeURIComponent(date)}`);
    if (!res.ok) return;
    const data = await res.json();
    if (!data.ok) return;

    const taken = data.taken_times || [];
    let availableCount = 0;

    timeSelect.querySelectorAll('option').forEach(opt => {
      if (!opt.value) return;
      const baseLabel = opt.dataset.label || opt.textContent;
      const isTaken = taken.includes(opt.value);
      opt.disabled = isTaken;
      opt.textContent = isTaken ? `${baseLabel} (Ocupado)` : baseLabel;
      if (!isTaken) availableCount += 1;
    });

    const placeholder = timeSelect.querySelector('option[value=""]');
    if (placeholder) {
      placeholder.textContent = availableCount > 0
        ? 'Selecciona una hora'
        : 'No hay horarios disponibles en esta fecha';
    }

    if (timeSelect.value && taken.includes(timeSelect.value)) {
      timeSelect.value = '';
    }
  } catch (err) {
    console.error('Error obteniendo disponibilidad (modal):', err);
  }
}

function showSuccessMessage() {
  const message = document.createElement('div');
  message.className = 'fixed top-4 right-4 bg-green-500 text-white px-6 py-4 rounded-lg shadow-lg z-[9999] animate-pulse';
  message.textContent = '✓ ¡Solicitud recibida! Te contactaremos pronto.';
  document.body.appendChild(message);
  setTimeout(() => message.remove(), 5000);
}

function showErrorMessage(customMessage) {
  const message = document.createElement('div');
  message.className = 'fixed top-4 right-4 bg-red-500 text-white px-6 py-4 rounded-lg shadow-lg z-[9999]';
  message.textContent = customMessage || '✗ Error al enviar. Por favor intenta de nuevo.';
  document.body.appendChild(message);
  setTimeout(() => message.remove(), 5000);
}
