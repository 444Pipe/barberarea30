<<<<<<< HEAD
/* Admin JS — shared utilities */
// (Loaded by base_admin.html)

=======
// Script para agregar interacción al admin
>>>>>>> 33d633d7e30239bdfeb32aca0e3c8201c45d5fc6
document.addEventListener('DOMContentLoaded', function() {
  // Agregar evento enter en inputs del login
  const inputs = document.querySelectorAll('input[type="text"], input[type="password"]');
  inputs.forEach(input => {
    input.addEventListener('keypress', function(e) {
      if (e.key === 'Enter') {
<<<<<<< HEAD
        const form = e.target.closest('form');
        if (form) form.submit();
=======
        e.target.closest('form').submit();
>>>>>>> 33d633d7e30239bdfeb32aca0e3c8201c45d5fc6
      }
    });
  });
});
