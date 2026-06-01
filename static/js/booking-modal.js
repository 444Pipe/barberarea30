
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

document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('booking-modal');
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        closeBookingModal();
      }
    });

    const closeBtn = modal.querySelector('[data-close-modal]');
    if (closeBtn) {
      closeBtn.addEventListener('click', closeBookingModal);
    }
  }

  // Establecer fecha mínima (hoy) para cualquier input de fecha
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  const todayStr = `${yyyy}-${mm}-${dd}`;

  const dateInput = document.getElementById('modal-date-input');
  if (dateInput) {
      dateInput.setAttribute('min', todayStr);
  }

  // Cargar servicios y barberos dinámicamente
  cargarModalServicios();
  cargarModalBarberos();

  // Escuchar cambios para cargar horarios
  const barberSelect = document.getElementById('modal-barber-select');
  const serviceSelect = document.getElementById('modal-service-select');

  if (barberSelect) barberSelect.addEventListener('change', tryLoadModalSlots);
  if (dateInput) dateInput.addEventListener('change', tryLoadModalSlots);
  if (serviceSelect) serviceSelect.addEventListener('change', tryLoadModalSlots);

  // Formulario de reserva en modal
  const form = document.getElementById('booking-form-modal');
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      const submitBtn = e.target.querySelector('button[type="submit"]');
      const originalBtnText = submitBtn ? submitBtn.textContent : '';

      const formData = new FormData(e.target);
      const name = formData.get('name')?.trim();
      const phone = formData.get('phone')?.trim();
      const email = formData.get('email')?.trim();
      const service = formData.get('service'); // This is the service ID or Name depending on options
      const barber = formData.get('barber');
      const date = formData.get('date');
      const time = formData.get('time');
      const notes = formData.get('notes')?.trim();

      if (!name || !phone || !email || !service || !date || !time) {
        showModalErrorMessage('Por favor completa todos los campos requeridos');
        return;
      }

      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(email)) {
        showModalErrorMessage('Por favor ingresa un email válido');
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Procesando...';
      }

      const selectedOption = serviceSelect?.options[serviceSelect.selectedIndex];
      const serviceId = selectedOption?.dataset.serviceId || selectedOption?.value;
      const servicePrice = selectedOption?.dataset.price || 0;

      const payload = {
        client_name: name,
        client_phone: phone,
        client_email: email,
        service_id: serviceId,
        barber_id: barber || 'any',
        date,
        time,
        price: servicePrice,
        notes: notes,
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
          showModalSuccessMessage();
          form.reset();
          document.getElementById('modal-time-select').innerHTML = '<option value="">Selecciona barbero y fecha primero</option>';
          if (submitBtn) submitBtn.textContent = '✓ Reserva enviada';
          setTimeout(() => closeBookingModal(), 2000);
        } else {
          const errMsg = result.error || result.errors || 'Error al guardar la reserva. Intenta de nuevo.';
          showModalErrorMessage(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg));
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = originalBtnText;
          }
        }
      } catch (error) {
        console.error('Error al crear reserva (modal):', error);
        showModalErrorMessage('Ocurrió un error al enviar la reserva.');
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalBtnText;
        }
      }
    });
  }
});

function cargarModalServicios() {
  fetch('/api/servicios-nativos/')
    .then(response => {
      if (!response.ok) throw new Error("Error en servicios");
      return response.json();
    })
    .then(data => {
      const select = document.getElementById('modal-service-select');
      if (!select) return;
      
      let optionsHtml = '<option value="" class="bg-jet">Selecciona un servicio</option>';
      data.servicios.forEach(servicio => {
        // Servicios "a consulta" (ej. Color) no se reservan por modal rápido —
        // el cliente los inicia desde el wizard de booking, que abre WhatsApp.
        if (servicio.requires_consultation) return;
        const precioFormat = parseFloat(servicio.price).toLocaleString('es-CO');
        optionsHtml += `<option value="${servicio.name}" data-service-id="${servicio.id}" data-price="${servicio.price}" class="bg-jet">${servicio.name} - $${precioFormat}</option>`;
      });
      select.innerHTML = optionsHtml;
    })
    .catch(err => {
      console.error(err);
      const select = document.getElementById('modal-service-select');
      if (select) select.innerHTML = '<option value="" class="bg-jet">Error al cargar servicios</option>';
    });
}

function cargarModalBarberos() {
  fetch('/api/barberos-nativos/')
    .then(response => {
      if (!response.ok) throw new Error("Error en barberos");
      return response.json();
    })
    .then(data => {
      const select = document.getElementById('modal-barber-select');
      if (!select) return;
      
      let optionsHtml = '<option value="" class="bg-jet">Cualquier Barbero Disponible</option>';
      data.barberos.forEach(barbero => {
        optionsHtml += `<option value="${barbero.id}" class="bg-jet">${barbero.nombre} (${barbero.especialidad || 'Barbero'})</option>`;
      });
      select.innerHTML = optionsHtml;
    })
    .catch(err => {
      console.error(err);
      const select = document.getElementById('modal-barber-select');
      if (select) select.innerHTML = '<option value="" class="bg-jet">Error al cargar barberos</option>';
    });
}

const MODAL_HOUR_LABELS = {
  '09:00': '09:00 AM', '10:00': '10:00 AM', '11:00': '11:00 AM',
  '12:00': '12:00 PM', '13:00': '01:00 PM', '14:00': '02:00 PM',
  '15:00': '03:00 PM', '16:00': '04:00 PM', '17:00': '05:00 PM',
  '18:00': '06:00 PM', '19:00': '07:00 PM', '20:00': '08:00 PM',
};

function tryLoadModalSlots() {
  const barberId  = document.getElementById('modal-barber-select')?.value || 'any';
  const date      = document.getElementById('modal-date-input')?.value;
  const serviceEl = document.getElementById('modal-service-select');
  const serviceId = serviceEl?.options[serviceEl.selectedIndex]?.dataset?.serviceId
                    || serviceEl?.value
                    || null;
  if (date && serviceId) {
    loadModalAvailableSlots(barberId, date, serviceId);
  }
}

async function loadModalAvailableSlots(barberId, date, serviceId) {
  const timeSelect = document.getElementById('modal-time-select');
  const hint       = document.getElementById('modal-time-hint');
  const durationBadge = document.getElementById('modal-service-duration-badge');
  if (!timeSelect) return;

  timeSelect.innerHTML = '<option value="">Cargando horarios...</option>';
  timeSelect.disabled = true;

  try {
    let url = `/api/barbers/${barberId}/availability/?date=${date}`;
    if (serviceId) url += `&service_id=${serviceId}`;

    const res  = await fetch(url);
    const data = await res.json();

    if (data.day_off) {
      timeSelect.innerHTML = '<option value="">Sin horario este día</option>';
      if (hint) hint.classList.add('hidden');
      if (durationBadge) durationBadge.classList.add('hidden');
      return;
    }

    if (durationBadge) {
      const dur = data.service_duration || 60;
      if (dur > 60) {
        durationBadge.textContent = `⏱ Este servicio dura ${dur} min y bloquea ${data.slots_needed} hora${data.slots_needed > 1 ? 's' : ''} consecutivas`;
        durationBadge.classList.remove('hidden');
      } else {
        durationBadge.classList.add('hidden');
      }
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
      const label = MODAL_HOUR_LABELS[slot.time] || slot.time;
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

function showModalSuccessMessage() {
  const message = document.createElement('div');
  message.className = 'fixed top-4 right-4 bg-emerald-600 text-white px-6 py-4 rounded-lg shadow-lg z-[9999]';
  message.textContent = '✓ ¡Solicitud recibida! Te contactaremos pronto por WhatsApp';
  document.body.appendChild(message);
  setTimeout(() => message.remove(), 6000);
}

function showModalErrorMessage(customMessage) {
  const message = document.createElement('div');
  message.className = 'fixed top-4 right-4 bg-red-600 text-white px-6 py-4 rounded-lg shadow-lg z-[9999] max-w-sm';
  message.textContent = customMessage || '✗ Error al enviar. Por favor intenta de nuevo.';
  document.body.appendChild(message);
  setTimeout(() => message.remove(), 6000);
}
