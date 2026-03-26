/* Admin JS — shared utilities */
// (Loaded by base_admin.html)

document.addEventListener('DOMContentLoaded', function() {
  // Agregar evento enter en inputs del login
  const inputs = document.querySelectorAll('input[type="text"], input[type="password"]');
  inputs.forEach(input => {
    input.addEventListener('keypress', function(e) {
      if (e.key === 'Enter') {
        const form = e.target.closest('form');
        if (form) form.submit();
      }
    });
  });
});
