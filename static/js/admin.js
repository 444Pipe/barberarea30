// Script para agregar interacción al admin
document.addEventListener('DOMContentLoaded', function() {
  // Agregar evento enter en inputs del login
  const inputs = document.querySelectorAll('input[type="text"], input[type="password"]');
  inputs.forEach(input => {
    input.addEventListener('keypress', function(e) {
      if (e.key === 'Enter') {
        e.target.closest('form').submit();
      }
    });
  });
});
