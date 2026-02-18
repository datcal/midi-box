/* =========================================================================
   MIDI Box - Web UI JavaScript
   ========================================================================= */

// State
let currentPage = 'dashboard';
let devices = [];
let routes = [];
let presets = [];
let currentPreset = null;
let monitorPaused = false;
let pollInterval = null;
let monitorInterval = null;
let logInterval = null;

// --- Navigation ---

document.querySelectorAll('[data-page]').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    const page = link.dataset.page;
    navigateTo(page);
  });
});

function navigateTo(page) {
  currentPage = page;
  // Update nav active state
  document.querySelectorAll('[data-page]').forEach(a => a.classList.remove('active'));
  document.querySelector(`[data-page="${page}"]`)?.classList.add('active');
  // Show page
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById(`page-${page}`)?.classList.add('active');
  // Load page data
  loadPageData(page);
}

function loadPageData(page) {
  switch (page) {
    case 'dashboard': loadDashboard(); break;
    case 'routing': loadRouting(); break;
    case 'presets': loadPresets(); break;
    case 'monitor': startMonitor(); break;
    case 'settings': loadSettings(); break;
    case 'logs': startLogs(); break;
  }
}

// --- API helpers ---

async function api(path, opts = {}) {
  const resp = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  return resp.json();
}

// --- Dashboard ---

async function loadDashboard() {
  const [devData, routeData, monData] = await Promise.all([
    api('/devices'),
    api('/routes'),
    api('/monitor?limit=1'),
  ]);

  devices = devData.devices;
  routes = routeData.routes;
  document.getElementById('mode-badge').textContent = devData.mode;

  // Stats
  document.getElementById('stat-devices').textContent = devices.length;
  document.getElementById('stat-routes').textContent = routes.length;
  document.getElementById('stat-messages').textContent = monData.stats.total || 0;
  document.getElementById('device-count').textContent = devices.length;

  // Device list
  const list = document.getElementById('device-list');
  if (devices.length === 0) {
    list.innerHTML = '<div style="padding:20px; color:var(--text-muted); text-align:center;">No MIDI devices detected. Connect a device and click Rescan.</div>';
    return;
  }

  list.innerHTML = devices.map(d => `
    <div class="device-card">
      <div class="device-name">${esc(d.name)}</div>
      <div class="device-meta">
        ${d.port_type.toUpperCase()} &middot; ${d.direction} &middot; ${d.device_type}
        ${d.midi_channel ? ' &middot; ch ' + d.midi_channel : ''}
      </div>
      <div class="device-activity">
        <span class="activity-dot ${d.activity_in ? 'active-in' : ''}" title="IN: ${d.msg_count_in} msgs"></span>
        <span class="activity-dot ${d.activity_out ? 'active-out' : ''}" title="OUT: ${d.msg_count_out} msgs"></span>
        <span style="font-size:11px; color:var(--text-muted); margin-left:4px;">
          IN:${d.msg_count_in} OUT:${d.msg_count_out}
        </span>
      </div>
    </div>
  `).join('');
}

async function rescanDevices() {
  await api('/settings/rescan', { method: 'POST' });
  loadDashboard();
}

// --- Routing ---

let pendingFilterRoute = null;

async function loadRouting() {
  const [devData, routeData] = await Promise.all([
    api('/devices'),
    api('/routes'),
  ]);
  devices = devData.devices;
  routes = routeData.routes;

  renderRoutingMatrix();
  renderRouteList();
}

function renderRoutingMatrix() {
  const inputDevs = devices.filter(d => d.direction === 'both' || d.direction === 'in');
  const outputDevs = devices.filter(d => d.direction === 'both' || d.direction === 'out');

  if (inputDevs.length === 0 || outputDevs.length === 0) {
    document.getElementById('routing-matrix').innerHTML =
      '<div style="padding:20px; color:var(--text-muted); text-align:center;">No devices available for routing.</div>';
    return;
  }

  // Build route lookup
  const routeSet = new Set(routes.map(r => `${r.from}|${r.to}`));

  let html = '<table><thead><tr><th class="row-header">FROM \\ TO</th>';
  outputDevs.forEach(d => {
    html += `<th title="${esc(d.name)}">${esc(shortName(d.name))}</th>`;
  });
  html += '</tr></thead><tbody>';

  inputDevs.forEach(src => {
    html += `<tr><th class="row-header">${esc(src.name)}</th>`;
    outputDevs.forEach(dst => {
      const key = `${src.name}|${dst.name}`;
      const isSelf = src.name === dst.name;
      const isRouted = routeSet.has(key);

      if (isSelf) {
        html += '<td class="cell self">&mdash;</td>';
      } else {
        html += `<td class="cell ${isRouted ? 'routed' : ''}"
                     onclick="toggleRoute('${esc(src.name)}','${esc(dst.name)}',${isRouted})"
                     oncontextmenu="editRouteFilter(event,'${esc(src.name)}','${esc(dst.name)}')"
                     title="${esc(src.name)} &rarr; ${esc(dst.name)}">
                   ${isRouted ? '&#10003;' : ''}
                 </td>`;
      }
    });
    html += '</tr>';
  });

  html += '</tbody></table>';
  document.getElementById('routing-matrix').innerHTML = html;
}

function renderRouteList() {
  const list = document.getElementById('route-list');
  if (routes.length === 0) {
    list.innerHTML = '<li class="route-item" style="color:var(--text-muted);">No routes configured</li>';
    return;
  }

  list.innerHTML = routes.map(r => {
    const filterDesc = describeFilter(r.filter);
    return `
      <li class="route-item ${r.enabled === false ? 'disabled' : ''}">
        <div>
          <span class="route-path">
            <strong>${esc(r.from)}</strong>
            <span class="route-arrow">&rarr;</span>
            <strong>${esc(r.to)}</strong>
          </span>
          ${filterDesc ? `<span class="route-filter">${esc(filterDesc)}</span>` : ''}
        </div>
        <div class="btn-group">
          <button class="btn btn-sm" onclick="editRouteFilter(null,'${esc(r.from)}','${esc(r.to)}')">Filter</button>
          <button class="btn btn-sm" onclick="toggleRouteEnabled('${esc(r.from)}','${esc(r.to)}')">${r.enabled === false ? 'Enable' : 'Disable'}</button>
          <button class="btn btn-sm btn-danger" onclick="removeRoute('${esc(r.from)}','${esc(r.to)}')">Remove</button>
        </div>
      </li>`;
  }).join('');
}

async function toggleRoute(from, to, isRouted) {
  if (isRouted) {
    await api('/routes', { method: 'DELETE', body: { from, to } });
  } else {
    await api('/routes', { method: 'POST', body: { from, to, filter: {} } });
  }
  loadRouting();
}

async function removeRoute(from, to) {
  await api('/routes', { method: 'DELETE', body: { from, to } });
  loadRouting();
}

async function toggleRouteEnabled(from, to) {
  await api('/routes/toggle', { method: 'POST', body: { from, to } });
  loadRouting();
}

async function clearAllRoutes() {
  if (!confirm('Clear all routes?')) return;
  await api('/routes/clear', { method: 'POST' });
  loadRouting();
}

function editRouteFilter(event, from, to) {
  if (event) event.preventDefault();
  pendingFilterRoute = { from, to };
  const route = routes.find(r => r.from === from && r.to === to);
  const f = route?.filter || {};

  document.getElementById('filter-modal-info').textContent = `${from} → ${to}`;
  document.getElementById('filter-channels').value = (f.channels || []).join(',');
  document.getElementById('filter-remap').value = f.remap_channel || 0;
  document.getElementById('filter-types').value = (f.message_types || []).join(',');
  document.getElementById('filter-modal').classList.add('active');
}

function closeFilterModal() {
  document.getElementById('filter-modal').classList.remove('active');
  pendingFilterRoute = null;
}

async function applyFilter() {
  if (!pendingFilterRoute) return;
  const { from, to } = pendingFilterRoute;

  const channels = document.getElementById('filter-channels').value
    .split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n));
  const remap = parseInt(document.getElementById('filter-remap').value) || 0;
  const types = document.getElementById('filter-types').value
    .split(',').map(s => s.trim()).filter(Boolean);

  // Remove old route and create new one with filter
  await api('/routes', { method: 'DELETE', body: { from, to } });
  await api('/routes', {
    method: 'POST',
    body: {
      from, to,
      filter: {
        ...(channels.length ? { channels } : {}),
        ...(remap ? { remap_channel: remap } : {}),
        ...(types.length ? { message_types: types } : {}),
      }
    }
  });

  closeFilterModal();
  loadRouting();
}

function describeFilter(f) {
  if (!f) return '';
  const parts = [];
  if (f.channels?.length) parts.push(`ch ${f.channels.join(',')}`);
  if (f.remap_channel) parts.push(`→ch ${f.remap_channel}`);
  if (f.message_types?.length) parts.push(f.message_types.join(','));
  if (f.block_clock) parts.push('no clock');
  return parts.join(' | ');
}

// --- Presets ---

async function loadPresets() {
  const data = await api('/presets');
  presets = data.presets;
  currentPreset = data.current;

  const list = document.getElementById('preset-list');
  if (presets.length === 0) {
    list.innerHTML = '<li class="preset-item" style="color:var(--text-muted);">No presets found</li>';
    return;
  }

  // Load details for each preset
  const details = await Promise.all(presets.map(name => api(`/presets/${name}`)));

  list.innerHTML = presets.map((name, i) => {
    const d = details[i];
    const isCurrent = name === currentPreset;
    return `
      <li class="preset-item ${isCurrent ? 'current' : ''}" onclick="loadPreset('${esc(name)}')">
        <div>
          <div class="preset-name">${esc(d.name || name)} ${isCurrent ? '(active)' : ''}</div>
          <div class="preset-desc">${esc(d.description || '')} &middot; ${(d.routes||[]).length} routes</div>
        </div>
        <div class="btn-group">
          <button class="btn btn-sm btn-accent" onclick="event.stopPropagation(); loadPreset('${esc(name)}')">Load</button>
          <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deletePreset('${esc(name)}')">Delete</button>
        </div>
      </li>`;
  }).join('');
}

async function loadPreset(name) {
  await api(`/presets/${name}/load`, { method: 'POST' });
  currentPreset = name;
  loadPresets();
}

async function deletePreset(name) {
  if (!confirm(`Delete preset "${name}"?`)) return;
  await api(`/presets/${name}`, { method: 'DELETE' });
  loadPresets();
}

async function saveCurrentAsPreset() {
  const name = prompt('Preset name:', 'custom');
  if (!name) return;
  const desc = prompt('Description:', '');
  await api('/presets/save', {
    method: 'POST',
    body: { name: name.toLowerCase().replace(/\s+/g, '_'), display_name: name, description: desc || '' }
  });
  loadPresets();
}

// --- MIDI Monitor ---

function startMonitor() {
  if (monitorInterval) clearInterval(monitorInterval);
  monitorInterval = setInterval(refreshMonitor, 200);
  refreshMonitor();
}

async function refreshMonitor() {
  if (monitorPaused) return;
  if (currentPage !== 'monitor') {
    clearInterval(monitorInterval);
    monitorInterval = null;
    return;
  }

  const showClock = document.getElementById('monitor-filter-clock').checked;
  const showAS = document.getElementById('monitor-filter-active-sensing').checked;

  const data = await api('/monitor?limit=200');
  document.getElementById('monitor-total').textContent = data.stats.total || 0;

  let entries = data.entries;
  if (!showClock) entries = entries.filter(e => e.msg_type !== 'clock');
  if (!showAS) entries = entries.filter(e => e.msg_type !== 'active_sensing');

  const body = document.getElementById('monitor-body');
  body.innerHTML = entries.slice(0, 200).map(e => {
    const dirClass = `dir-${e.direction}`;
    const typeClass = e.msg_type.startsWith('note') ? 'msg-note'
      : e.msg_type === 'control_change' ? 'msg-cc'
      : e.msg_type === 'clock' ? 'msg-clock' : '';

    return `<tr>
      <td>${e.time_str}.${e.time_ms}</td>
      <td class="${dirClass}">${e.direction.toUpperCase()}</td>
      <td>${esc(e.source || '-')}</td>
      <td>${esc(e.destination || '-')}</td>
      <td class="${typeClass}">${esc(e.msg_type)}</td>
      <td>${e.channel >= 0 ? e.channel : '-'}</td>
      <td>${esc(e.data)}</td>
      <td style="color:var(--text-muted); font-size:11px;">${esc(e.raw)}</td>
    </tr>`;
  }).join('');
}

function toggleMonitor() {
  monitorPaused = !monitorPaused;
  const btn = document.getElementById('monitor-toggle');
  btn.textContent = monitorPaused ? 'Resume' : 'Pause';

  if (monitorPaused) {
    api('/monitor/pause', { method: 'POST' });
  } else {
    api('/monitor/resume', { method: 'POST' });
  }
}

async function clearMonitor() {
  await api('/monitor/clear', { method: 'POST' });
  document.getElementById('monitor-body').innerHTML = '';
}

// --- Settings ---

async function loadSettings() {
  const data = await api('/settings');
  document.getElementById('setting-platform').value = data.platform;
  document.getElementById('setting-mode').value = data.mode;
  document.getElementById('setting-preset').value = data.preset || '(none)';

  // Populate clock source dropdown
  const devData = await api('/devices');
  const select = document.getElementById('setting-clock-source');
  select.innerHTML = '<option value="">None</option>';
  devData.devices.forEach(d => {
    const selected = d.name === data.clock_source ? 'selected' : '';
    select.innerHTML += `<option value="${esc(d.name)}" ${selected}>${esc(d.name)}</option>`;
  });
}

async function setClockSource() {
  const source = document.getElementById('setting-clock-source').value || null;
  await api('/settings/clock', { method: 'POST', body: { source } });
}

// --- Export / Import ---

async function importState(input) {
  const file = input.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  const resp = await fetch('/api/import', { method: 'POST', body: formData });
  const data = await resp.json();

  if (data.ok) {
    alert(`Imported successfully: ${data.routes} routes restored.`);
    loadSettings();
    // Reset file input so same file can be re-imported
    input.value = '';
  } else {
    alert(`Import failed: ${data.error}`);
  }
}

async function resetState() {
  if (!confirm('Reset all state to defaults? This will clear all routes.')) return;
  await api('/state/reset', { method: 'POST' });
  alert('State reset to defaults.');
  loadSettings();
}

// --- Logs ---

function startLogs() {
  if (logInterval) clearInterval(logInterval);
  logInterval = setInterval(refreshLogs, 1000);
  refreshLogs();
}

async function refreshLogs() {
  if (currentPage !== 'logs') {
    clearInterval(logInterval);
    logInterval = null;
    return;
  }

  const data = await api('/logs');
  const viewer = document.getElementById('log-viewer');
  viewer.innerHTML = data.entries.map(e => `
    <div class="log-entry">
      <span class="log-time">${esc(e.time)}</span>
      <span class="log-level ${e.level}">${e.level}</span>
      <span class="log-name">${esc(e.name)}</span>
      <span class="log-msg">${esc(e.message)}</span>
    </div>
  `).join('');
}

async function clearLogs() {
  await api('/logs/clear', { method: 'POST' });
  document.getElementById('log-viewer').innerHTML = '';
}

// --- Utilities ---

function shortName(name) {
  // Shorten device names for matrix header
  const map = {
    'KeyLab 88 MK2': 'KLab88',
    'KeyStep': 'KStep',
    'Behringer Model D': 'ModD',
    'Roland JP-08': 'JP08',
    'MicroBrute': 'MBrute',
    'SP-404 MK2': 'SP404',
    'MS-20 Mini': 'MS20',
    'Volca 1': 'Vol1',
    'Volca 2': 'Vol2',
    'Volca 3': 'Vol3',
    'Logic Pro': 'Logic',
  };
  return map[name] || name.substring(0, 8);
}

function esc(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// --- Polling for activity updates (dashboard) ---

function startPolling() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    if (currentPage === 'dashboard') {
      loadDashboard();
    }
  }, 2000);
}

// --- Hash-based navigation ---

function handleHash() {
  const hash = window.location.hash.replace('#', '') || 'dashboard';
  navigateTo(hash);
}

window.addEventListener('hashchange', handleHash);

// --- Init ---

document.addEventListener('DOMContentLoaded', () => {
  handleHash();
  startPolling();
});
