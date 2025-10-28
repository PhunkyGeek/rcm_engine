// File encode helpers & validation flow
async function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result;
      const base64 = String(dataUrl).split(',')[1];
      resolve(base64);
    };
    reader.onerror = err => reject(err);
    reader.readAsDataURL(file);
  });
}

window.validateFiles = async function validateFiles() {
  const uploadMsg = document.getElementById('upload-message');
  uploadMsg.textContent = '';

  const tenant = (document.getElementById('tenantId').value || '').trim() || 'default';
  // Expose current tenant early so other helpers can pick it up during upload
  window.currentTenant = tenant;

  const files = [
    { key: 'claims', input: 'claimsInput' },
    { key: 'tech', input: 'techInput' },
    { key: 'medical', input: 'medicalInput' }
  ];

  const circles = {};
  const paths = {};
  const percents = {};
  const statuses = {};

  files.forEach(f => {
    circles[f.key] = document.getElementById(`${f.key}Circle`);
    paths[f.key] = document.getElementById(`${f.key}ProgressPath`);
    percents[f.key] = document.getElementById(`${f.key}Percent`);
    statuses[f.key] = document.getElementById(`${f.key}Status`);
    circles[f.key].style.display = 'none';
    circles[f.key].classList.remove('success', 'error');
    percents[f.key].textContent = '0%';
  });

  const claimsFile = document.getElementById('claimsInput').files[0];
  if (!claimsFile) {
    uploadMsg.style.color = 'var(--colour-error)';
    uploadMsg.textContent = 'Please select a claims file.';
    return;
  }

  const techFile = document.getElementById('techInput').files[0];
  const medFile = document.getElementById('medicalInput').files[0];

  const showCircle = key => (circles[key].style.display = 'block');
  const hideCirclesLater = () =>
    setTimeout(() => {
      Object.values(circles).forEach(c => (c.style.display = 'none'));
    }, 10000);

  try {
    uploadMsg.style.color = 'var(--colour-info)';
    uploadMsg.textContent = 'Uploading files…';

  const techText = techFile ? { filename: techFile.name, content: await fileToBase64(techFile) } : null;
  const medText = medFile ? { filename: medFile.name, content: await fileToBase64(medFile) } : null;

    const claimsB64 = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = e => resolve(String(e.target.result).split(',')[1]);
      reader.onerror = reject;
      reader.readAsDataURL(claimsFile);
    });

    showCircle('claims');
    statuses.claims.textContent = 'Preparing upload…';

    await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/upload', true);
      xhr.setRequestHeader('Content-Type', 'application/json');

      let lastLoaded = 0;
      let lastTime = Date.now();

      xhr.upload.onprogress = e => {
        if (e.lengthComputable) {
          const percent = ((e.loaded / e.total) * 100).toFixed(1);
          const circumference = 100;
          paths.claims.setAttribute('stroke-dasharray', `${percent}, 100`);
          percents.claims.textContent = `${Math.round(percent)}%`;

          const now = Date.now();
          const timeDiff = (now - lastTime) / 1000;
          const bytesDiff = e.loaded - lastLoaded;
          const speed = bytesDiff / timeDiff;
          lastLoaded = e.loaded;
          lastTime = now;

          const humanSpeed =
            speed > 1e6 ? (speed / 1e6).toFixed(1) + ' MB/s' : (speed / 1e3).toFixed(1) + ' KB/s';
          const uploadedMB = (e.loaded / 1e6).toFixed(2);
          const totalMB = (e.total / 1e6).toFixed(2);
          statuses.claims.textContent = `Uploading ${uploadedMB}/${totalMB} MB @ ${humanSpeed}`;
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
            paths.claims.setAttribute('stroke-dasharray', '100, 100');
            circles.claims.classList.add('success');
            // The UI previously tried to update `bars.claims` which doesn't exist
            // (ReferenceError). Use the claims card styling instead so we don't
            // throw and prevent the upload flow from completing.
            const claimsCard = document.getElementById('claimsCard');
            if (claimsCard) claimsCard.style.borderColor = 'var(--colour-success)';
          statuses.claims.textContent = '✅ Upload complete!';
          uploadMsg.style.color = 'var(--colour-success)';
          uploadMsg.textContent = 'Files uploaded successfully. Starting validation...';

          resolve();
        } else {
          circles.claims.classList.add('error');
          statuses.claims.textContent = '❌ Upload failed';
          reject(new Error('Upload failed'));
        }
      };
      xhr.onerror = () => reject(new Error('Network error'));

      xhr.send(
        JSON.stringify({
          tenant_id: tenant,
          claims_file: claimsB64,
          technical_rules_file: techText,
          medical_rules_file: medText
        })
      );
    });

    uploadMsg.textContent = 'Validating claims…';
    const validateRes = await fetch(`/validate/${tenant}`, { method: 'POST' });
    if (!validateRes.ok) {
      const txt = await validateRes.text().catch(() => 'Validation failed');
      throw new Error(txt || 'Validation failed');
    }

    const v = await validateRes.json();
    // Display success or failure prominently
    const processed = v.processed || (v.claims || []).length || 0;
    const failed = (v.claims || []).filter(c => (c.error_type || c.status || '').toLowerCase() !== 'no error' && (c.error_type || '').toLowerCase() !== 'noerror').length;
    if (failed > 0) {
      uploadMsg.style.color = 'var(--colour-error)';
      uploadMsg.textContent = `❌ Validation complete — ${processed} processed, ${failed} failed checks.`;
    } else {
      uploadMsg.style.color = 'var(--colour-success)';
      uploadMsg.textContent = `✅ Validation complete — ${processed} processed, no errors found.`;
    }

    // Normalize claims returned by validate() to the shape expected by the renderer
    const normalized = (v.claims || []).map(c => ({
      claim_id: c.claim_id || c.claimId || c.id || '',
      status: c.status || (c.error_type && c.error_type !== 'No error' ? 'Not validated' : 'Validated') || 'Validated',
      error_type: c.error_type || c.errorType || 'No error',
      error_explanation: c.error_explanation || c.explanation || c.errorExplanation || 'No issues',
      recommended_action: c.recommended_action || c.recommendedAction || ''
    }));

    window.allClaims = normalized;
    window.renderResultsTable(window.allClaims);
    window.renderCharts(v.metrics || []);
    // Show the results view
    window.currentTenant = tenant;
    await window.fetchResultsAndMetrics();
    window.showPage('results');
  } catch (err) {
    uploadMsg.style.color = 'var(--colour-error)';
    uploadMsg.textContent = `❌ ${err.message}`;
    Object.values(circles).forEach(c => {
      c.style.display = 'block';
      c.classList.add('error');
    });
    Object.values(statuses).forEach(s => (s.textContent = 'Failed'));
    hideCirclesLater();
  }
};

// seedSampleRules / clearTenantData / showRefined removed — upload UI now only performs upload+validate

['claims', 'tech', 'medical'].forEach(type => {
  document.getElementById(`${type}Input`).addEventListener('change', e => {
    const file = e.target.files[0];
    if (file) {
      const circle = document.getElementById(`${type}Circle`);
      const percent = document.getElementById(`${type}Percent`);
      const status = document.getElementById(`${type}Status`);
      const path = document.getElementById(`${type}ProgressPath`);

      circle.style.display = 'block';
      circle.classList.remove('success', 'error');
      path.setAttribute('stroke-dasharray', '100, 100');
      percent.textContent = '✔';
      status.innerHTML = `<b>${file.name}</b> (${(file.size / 1024).toFixed(1)} KB) ready`;
    }
  });
});


document.getElementById('claimsInput').addEventListener('change', e => {
  showFileStatus('claims', e.target.files[0]);
});
document.getElementById('techInput').addEventListener('change', e => {
  showFileStatus('tech', e.target.files[0]);
});
document.getElementById('medicalInput').addEventListener('change', e => {
  showFileStatus('medical', e.target.files[0]);
});

function showFileStatus(type, file) {
  if (!file) return;

  const circle = document.getElementById(`${type}Circle`);
  const percent = document.getElementById(`${type}Percent`);
  const status = document.getElementById(`${type}Status`);
  const path = document.getElementById(`${type}ProgressPath`);

  circle.style.display = 'block';
  circle.classList.remove('success', 'error');
  path.setAttribute('stroke-dasharray', '100, 100');
  percent.textContent = '✔';
  status.innerHTML = `<b>${file.name}</b> (${(file.size / 1024).toFixed(1)} KB) selected`;
}


window.fetchResultsAndMetrics = async function fetchResultsAndMetrics() {
  const tenant = window.currentTenant || 'default';
  try {
    const res = await fetch(`/results/${tenant}`);
    const resJson = await res.json();
    window.allClaims = resJson.claims || [];
    window.renderResultsTable(window.allClaims);

    const met = await fetch(`/metrics/${tenant}`);
    const metJson = await met.json();
    const metrics = metJson.metrics || [];
    window.renderCharts(metrics);
  } catch (err) {
    console.error('Failed to fetch results/metrics', err);
  }
};
