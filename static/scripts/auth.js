// Authentication
window.loginUser = async function loginUser() {
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;
  const errorEl = document.getElementById('login-error');
  errorEl.style.display = 'none';
  try {
    const response = await fetch('/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    if (!response.ok) throw new Error('Invalid username or password');

    document.getElementById('login-page').style.display = 'none';
    document.getElementById('main-app').classList.remove('hidden');
    window.currentTenant = '';
    window.allClaims = [];
    window.showPage('dashboard');
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.style.display = 'block';
  }
};

window.logoutUser = function logoutUser() {
  document.getElementById('main-app').classList.add('hidden');
  document.getElementById('login-page').style.display = 'flex';
  document.getElementById('username').value = '';
  document.getElementById('password').value = '';
  // close dropdown
  const d = document.getElementById('userDropdown');
  d && d.classList.remove('show');
};
