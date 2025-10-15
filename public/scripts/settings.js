// Simple settings UI client for tenant-configurable engine

window.loadSettings = async function loadSettings() {
  const tenant = (document.getElementById('settingsTenant').value || '').trim();
  const msg = document.getElementById('settingsMsg');
  msg.textContent = '';
  if (!tenant) {
    msg.textContent = 'Enter tenant id first';
    return;
  }
  try {
    const res = await fetch(`/settings/${tenant}`);
    if (!res.ok) throw new Error('Failed to load settings');
    const j = await res.json();
    const cfg = j.config || {};
    if (cfg.paid_amount_approval_threshold) {
      document.getElementById('paidThreshold').value = cfg.paid_amount_approval_threshold;
    } else {
      document.getElementById('paidThreshold').value = '';
    }
    // load caps if present (JSON)
    if (cfg.paid_amount_caps) {
      try {
        const caps = JSON.parse(cfg.paid_amount_caps);
        window._caps = caps || [];
      } catch (e) {
        window._caps = [];
      }
    } else {
      window._caps = [];
    }
    renderCaps();
    msg.textContent = 'Loaded settings for ' + tenant;
  } catch (e) {
    msg.textContent = 'Error loading settings: ' + e.message;
  }
}

window.saveSettings = async function saveSettings() {
  const tenant = (document.getElementById('settingsTenant').value || '').trim();
  const msg = document.getElementById('settingsMsg');
  msg.textContent = '';
  if (!tenant) {
    msg.textContent = 'Enter tenant id first';
    return;
  }
  const threshold = document.getElementById('paidThreshold').value;
  const caps = window._caps || [];
  try {
    const res = await fetch(`/settings/${tenant}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paid_amount_approval_threshold: threshold, paid_amount_caps: JSON.stringify(caps) }) });
    if (!res.ok) throw new Error(await res.text());
    msg.textContent = 'Settings saved for ' + tenant;
  } catch (e) {
    msg.textContent = 'Error saving settings: ' + e.message;
  }
}

// Caps UI management
window._caps = window._caps || [];

function renderCaps() {
  const containerId = 'capsContainer';
  let container = document.getElementById(containerId);
  if (!container) {
    // create container in settings area
    const settingsArea = document.getElementById('settings');
    const card = document.createElement('div');
    card.className = 'caps-card';
    card.innerHTML = `
      <h4>Paid Amount Caps per Service Code</h4>
      <div id="capsEmpty" class="caps-empty">No thresholds defined.</div>
      <div class="caps-row">
        <input id="capService" placeholder="Service Code" />
        <input id="capAmount" placeholder="Cap (AED)" type="number" />
        <button id="capAddBtn" class="btn btn-primary">Add</button>
      </div>
      <table class="caps-table" id="capsTable"><thead><tr><th>Service Code</th><th>Cap (AED)</th><th></th></tr></thead><tbody></tbody></table>
      <div style="margin-top:12px;"><button id="saveCapsBtn" class="btn btn-success">Save Thresholds</button></div>
    `;
    settingsArea.appendChild(card);
    container = card;
    document.getElementById('capAddBtn').addEventListener('click', addCap);
    document.getElementById('saveCapsBtn').addEventListener('click', () => {
      // trigger save
      saveSettings();
    });
  }
  const tblBody = container.querySelector('#capsTable tbody');
  tblBody.innerHTML = '';
  if (!window._caps || window._caps.length === 0) {
    document.getElementById('capsEmpty').style.display = 'block';
    container.querySelector('#capsTable').style.display = 'none';
  } else {
    document.getElementById('capsEmpty').style.display = 'none';
    container.querySelector('#capsTable').style.display = 'table';
    window._caps.forEach((c, idx) => {
      const tr = document.createElement('tr');
      const a = document.createElement('td'); a.textContent = c.service || '';
      const b = document.createElement('td'); b.textContent = c.cap || '';
      const rm = document.createElement('td');
      const btn = document.createElement('button'); btn.className = 'caps-remove'; btn.textContent = 'Remove';
      btn.addEventListener('click', () => { removeCap(idx); });
      rm.appendChild(btn);
      tr.appendChild(a); tr.appendChild(b); tr.appendChild(rm);
      tblBody.appendChild(tr);
    });
  }
}

function addCap() {
  const svc = (document.getElementById('capService').value || '').trim();
  const amt = (document.getElementById('capAmount').value || '').trim();
  const msg = document.getElementById('settingsMsg');
  msg.textContent = '';
  if (!svc || !amt) {
    msg.textContent = 'Provide both service code and cap amount';
    return;
  }
  window._caps = window._caps || [];
  window._caps.push({ service: svc, cap: parseFloat(amt) });
  document.getElementById('capService').value = '';
  document.getElementById('capAmount').value = '';
  renderCaps();
}

function removeCap(idx) {
  window._caps.splice(idx, 1);
  renderCaps();
}

// Initialize caps UI when the script loads
document.addEventListener('DOMContentLoaded', renderCaps);
