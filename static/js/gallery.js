const filterButtons = document.querySelectorAll('.filter-btn');
const galleryItems = document.querySelectorAll('.gallery-item');

filterButtons.forEach(button => {
  button.addEventListener('click', () => {
    filterButtons.forEach(btn => btn.classList.remove('active'));
    button.classList.add('active');

    const filterValue = button.getAttribute('data-filter');

    galleryItems.forEach(item => {
      const itemCategory = item.getAttribute('data-category');

      if (filterValue === 'all' || itemCategory === filterValue) {
        item.style.display = 'block';
        setTimeout(() => {
          item.style.opacity = '1';
          item.style.transform = 'scale(1)';
        }, 0);
      } else {
        item.style.opacity = '0';
        item.style.transform = 'scale(0.95)';
        setTimeout(() => {
          item.style.display = 'none';
        }, 300);
      }
    });
  });
});

galleryItems.forEach(item => {
  item.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
  item.style.opacity = '1';
  item.style.transform = 'scale(1)';
});
