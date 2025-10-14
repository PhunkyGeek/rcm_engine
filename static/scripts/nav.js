// Navigation & dropdown
window.showPage = function showPage(page) {
  const pages = ['dashboard', 'results', 'upload', 'reports', 'settings'];
  pages.forEach(p => {
    const el = document.getElementById(p);
    if (!el) return;
    el.classList.toggle('hidden', p !== page);
  });
  const links = document.querySelectorAll('#navLinks a');
  links.forEach(link => {
    link.classList.toggle('active', link.getAttribute('data-page') === page);
  });
  // When user navigates to dashboard or results, ensure we fetch latest data
  if (page === 'dashboard' || page === 'results') {
    if (window.fetchResultsAndMetrics) window.fetchResultsAndMetrics();
  }
};

(function initDropdown(){
  const avatar = document.getElementById('avatarBtn');
  const dropdown = document.getElementById('userDropdown');
  if (!avatar || !dropdown) return;

  avatar.addEventListener('click', (e) => {
    e.stopPropagation();
    dropdown.classList.toggle('show');
    dropdown.classList.toggle('hidden', false);
  });

  window.addEventListener('click', (e) => {
    if (!dropdown.contains(e.target) && !avatar.contains(e.target)) {
      dropdown.classList.remove('show');
    }
  });
})();
