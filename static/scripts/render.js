// Rendering tables & charts
window.renderResultsTable = function renderResultsTable(claims) {
  const tbody = document.querySelector('#resultsTable tbody');
  tbody.innerHTML = '';
  if (!claims || claims.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted">No claims found.</td></tr>`;
    return;
  }

  claims.forEach(claim => {
    const tr = document.createElement('tr');

    const statusTd = document.createElement('td');
    const statusSpan = document.createElement('span');
    statusSpan.classList.add('status-pill');
    statusSpan.classList.add(claim.status === 'Validated' ? 'status-success' : 'status-error');
    statusSpan.textContent = claim.status === 'Validated' ? 'Success' : 'Error';
    statusTd.appendChild(statusSpan);

    const errorTd = document.createElement('td');
    errorTd.textContent = claim.error_type || '';

    const explTd = document.createElement('td');
    const explDiv = document.createElement('div');
    explDiv.classList.add('table-explanation');
    const explanation = claim.error_explanation || claim.explanation || '';
    if (explanation) {
      const ul = document.createElement('ul');
      explanation.split('\n').forEach(line => {
        const li = document.createElement('li');
        li.textContent = line.replace(/^\s*[-•]\s*/, '');
        ul.appendChild(li);
      });
      explDiv.appendChild(ul);
    }
    explTd.appendChild(explDiv);

    const actionTd = document.createElement('td');
    const actionDiv = document.createElement('div');
    actionDiv.classList.add('table-action');
    const actions = (claim.recommended_action || '').split(';').filter(Boolean);
    actions.forEach((a, i) => {
      const link = document.createElement('a');
      link.href = '#';
      link.textContent = a.trim();
      actionDiv.appendChild(link);
      if (i < actions.length - 1) {
        const sep = document.createElement('span');
        sep.textContent = ' | ';
        actionDiv.appendChild(sep);
      }
    });
    actionTd.appendChild(actionDiv);

    const idTd = document.createElement('td');
    idTd.textContent = claim.claim_id;

    tr.append(statusTd, errorTd, explTd, actionTd, idTd);
    tbody.appendChild(tr);
  });
};

window.filterResults = function filterResults() {
  const searchQuery = document.getElementById('resultsSearch').value.toLowerCase();
  const statusVal = document.getElementById('statusFilter').value;
  const errorVal = document.getElementById('errorFilter').value;
  const filtered = (window.allClaims || []).filter(claim => {
    const matchesSearch =
      (claim.claim_id || '').toLowerCase().includes(searchQuery) ||
      (claim.error_type || '').toLowerCase().includes(searchQuery) ||
      (claim.status || '').toLowerCase().includes(searchQuery);
    const matchesStatus = statusVal ? claim.status === statusVal : true;
    const matchesError = errorVal ? claim.error_type === errorVal : true;
    return matchesSearch && matchesStatus && matchesError;
  });
  window.renderResultsTable(filtered);
};

window.renderCharts = function renderCharts(metrics) {
  const countsContainer = document.getElementById('countsChart');
  const amountsContainer = document.getElementById('amountsChart');
  countsContainer.innerHTML = '';
  amountsContainer.innerHTML = '';

  if (!metrics || metrics.length === 0) {
    countsContainer.innerHTML = '<p class="muted small">No data available.</p>';
    amountsContainer.innerHTML = '<p class="muted small">No data available.</p>';
    return;
  }

  let totalCount = 0;
  let totalAmount = 0;
  metrics.forEach(m => {
    const count = parseFloat(m.count ?? m[1] ?? 0);
    const amt = parseFloat(m.amount ?? m[2] ?? 0);
    totalCount += count;
    totalAmount += Math.abs(amt);
  });

  metrics.forEach(m => {
    const category = m.category ?? m[0];
    const count = parseFloat(m.count ?? m[1] ?? 0);
    const amount = parseFloat(m.amount ?? m[2] ?? 0);
    const countPct = totalCount ? (count / totalCount) * 100 : 0;
    const amtPct = totalAmount ? (Math.abs(amount) / totalAmount) * 100 : 0;

    let barClass = 'info';
    if (category === 'No error') barClass = 'success';
    else if (category === 'Medical error') barClass = 'error';
    else if (category === 'Technical error') barClass = 'warning';

    // Count bars
    const rowCounts = document.createElement('div');
    rowCounts.className = 'bar-container';
    rowCounts.innerHTML = `
      <div class="bar-label">${category}</div>
      <div class="bar-track"><div class="bar-fill ${barClass}" style="width:${countPct}%"></div></div>
      <div class="bar-value">${count.toLocaleString()}</div>
    `;
    countsContainer.appendChild(rowCounts);

    // Amount bars
    const rowAmounts = document.createElement('div');
    rowAmounts.className = 'bar-container';
    let formattedAmt;
    if (Math.abs(amount) >= 1e6) formattedAmt = `${(amount / 1e6).toFixed(1)}M`;
    else if (Math.abs(amount) >= 1e3) formattedAmt = `${(amount / 1e3).toFixed(1)}k`;
    else formattedAmt = amount.toFixed(2);
    formattedAmt = (amount < 0 ? '-' : '') + 'AED ' + formattedAmt;

    rowAmounts.innerHTML = `
      <div class="bar-label">${category}</div>
      <div class="bar-track"><div class="bar-fill ${barClass}" style="width:${amtPct}%"></div></div>
      <div class="bar-value">${formattedAmt}</div>
    `;
    amountsContainer.appendChild(rowAmounts);
  });
};
