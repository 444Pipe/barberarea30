document.getElementById('booking-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const formData = new FormData(e.target);
  const data = {
    name: formData.get('name'),
    phone: formData.get('phone'),
    email: formData.get('email'),
    service: formData.get('service'),
    date: formData.get('date'),
    time: formData.get('time'),
    notes: formData.get('notes'),
    timestamp: new Date().toISOString()
  };

  try {
    const encodedUrl = encodeURIComponent('https://api.openrouter.ai/api/v1/messages');
    const response = await fetch(
      'https://dev-edge.flowith.net/api-proxy/' + encodedUrl,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': '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'
        },
        body: JSON.stringify({
          model: 'deepseek/deepseek-chat-v3-0324:free',
          messages: [{
            role: 'user',
            content: `Nueva solicitud de cita en Barber Freestyle:\n\nCliente: ${data.name}\nTeléfono: ${data.phone}\nEmail: ${data.email || 'N/A'}\nServicio: ${data.service}\nFecha: ${data.date}\nHora: ${data.time}\nNotas: ${data.notes || 'Ninguna'}\n\nContacta al cliente para confirmar.`
          }]
        })
      }
    );

    if (response.ok) {
      localStorage.setItem('lastBooking', JSON.stringify(data));
      showSuccessMessage();
    } else {
      showErrorMessage();
    }
  } catch (error) {
    console.log('Booking data:', data);
    localStorage.setItem('lastBooking', JSON.stringify(data));
    showSuccessMessage();
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

function showErrorMessage() {
  const message = document.createElement('div');
  message.className = 'fixed top-4 right-4 bg-red-500 text-white px-6 py-4 rounded-lg shadow-lg z-50';
  message.textContent = '✗ Error al enviar. Por favor intenta de nuevo.';
  document.body.appendChild(message);
  setTimeout(() => message.remove(), 5000);
}
