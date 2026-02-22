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
    case 'launcher': loadLauncher(); break;
    case 'presets': loadPresets(); break;
    case 'monitor': startMonitor(); break;
    case 'recorder': loadRecorder(); break;
    case 'looper': loadLooper(); break;
    case 'player': loadPlayer(); break;
    case 'settings': loadSettings(); break;
    case 'logs': startLogs(); break;
    case 'system': startSystem(); break;
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
        <span id="dot-in-${deviceId(d.name)}" class="activity-dot ${d.activity_in ? 'active-in' : ''}" title="IN: ${d.msg_count_in} msgs"></span>
        <span id="dot-out-${deviceId(d.name)}" class="activity-dot ${d.activity_out ? 'active-out' : ''}" title="OUT: ${d.msg_count_out} msgs"></span>
        <span id="count-${deviceId(d.name)}" style="font-size:11px; color:var(--text-muted); margin-left:4px;">
          IN:${d.msg_count_in} OUT:${d.msg_count_out}
        </span>
        <button class="btn btn-sm" style="margin-left:auto;" onclick="openDeviceModal('${esc(d.name)}')">Configure</button>
      </div>
    </div>
  `).join('');
}

// Lightweight dashboard update — only refreshes activity dots/counts.
// Called by the background poll instead of re-rendering the whole page.
function updateDashboardActivity(pollData) {
  for (const d of pollData.devices) {
    const id = deviceId(d.name);
    const dotIn  = document.getElementById(`dot-in-${id}`);
    const dotOut = document.getElementById(`dot-out-${id}`);
    const count  = document.getElementById(`count-${id}`);
    if (dotIn)  { dotIn.className  = `activity-dot ${d.active_in  ? 'active-in'  : ''}`; dotIn.title  = `IN: ${d.count_in} msgs`;  }
    if (dotOut) { dotOut.className = `activity-dot ${d.active_out ? 'active-out' : ''}`; dotOut.title = `OUT: ${d.count_out} msgs`; }
    if (count)  { count.textContent = `IN:${d.count_in} OUT:${d.count_out}`; }
  }
}

async function rescanDevices() {
  await api('/settings/rescan', { method: 'POST' });
  loadDashboard();
}

// --- Routing ---

let pendingFilterRoute = null;
let selectedSource = null;
let routingMode = 'perform'; // 'perform' | 'advanced'

// Controllers/keyboards are sources in Perform mode; synths/samplers are destinations
const CONTROLLER_TYPES = new Set(['controller', 'controller_sequencer']);

function deviceId(name) {
  return name.replace(/[^a-zA-Z0-9]/g, '_');
}

async function loadRouting() {
  const [devData, routeData] = await Promise.all([
    api('/devices'),
    api('/routes'),
  ]);
  devices = devData.devices;
  routes = routeData.routes;

  renderPatchbay();
  renderRouteList();
}

function setRoutingMode(mode) {
  routingMode = mode;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + mode)?.classList.add('active');
  selectedSource = null;
  renderPatchbay();
}

function renderPatchbay() {
  let sources, dests;

  if (routingMode === 'perform') {
    // Perform: keyboards → synths/samplers only
    sources = devices.filter(d =>
      CONTROLLER_TYPES.has(d.device_type) &&
      (d.direction === 'both' || d.direction === 'in')
    );
    dests = devices.filter(d =>
      !CONTROLLER_TYPES.has(d.device_type) &&
      (d.direction === 'both' || d.direction === 'out')
    );
  } else {
    // Advanced: all devices on both sides
    sources = devices.filter(d => d.direction === 'both' || d.direction === 'in');
    dests   = devices.filter(d => d.direction === 'both' || d.direction === 'out');
  }

  // Build route map: from -> Set of tos
  const routeMap = {};
  routes.forEach(r => {
    if (!routeMap[r.from]) routeMap[r.from] = new Set();
    routeMap[r.from].add(r.to);
  });

  // Validate selected source still exists in current view
  if (selectedSource && !sources.find(d => d.name === selectedSource)) {
    selectedSource = null;
  }

  const activeSet = (selectedSource && routeMap[selectedSource])
    ? routeMap[selectedSource] : new Set();
  const canTap = !!selectedSource;
  const exclusive = document.getElementById('exclusive-mode')?.checked;

  // --- Sources ---
  const sourcesEl = document.getElementById('patchbay-sources');
  sourcesEl.innerHTML = '<div class="pb-col-label">Sources</div>';

  if (sources.length === 0) {
    sourcesEl.innerHTML += '<div class="pb-empty">No source devices</div>';
  } else {
    sourcesEl.innerHTML += sources.map(d => {
      const isSelected = selectedSource === d.name;
      const routeCount = routeMap[d.name] ? routeMap[d.name].size : 0;
      const chLabel = d.midi_channel ? `ch ${d.midi_channel}` : 'all ch';
      return `
        <div id="src_${deviceId(d.name)}"
             class="pb-box ${isSelected ? 'pb-box-selected' : routeCount > 0 ? 'pb-box-active' : ''}"
             onclick="selectSource('${esc(d.name)}')">
          <div class="pb-box-label">${isSelected ? 'SELECTED' : 'SOURCE'}</div>
          <div class="pb-box-name">${esc(d.name)}</div>
          <div class="pb-box-meta">${chLabel} &middot; ${esc(d.device_type)}</div>
          ${routeCount > 0
            ? `<div class="pb-box-count">${routeCount} route${routeCount !== 1 ? 's' : ''}</div>`
            : ''}
        </div>`;
    }).join('');
  }

  // --- Destinations ---
  const destsEl = document.getElementById('patchbay-dests');
  destsEl.innerHTML = '<div class="pb-col-label">Destinations</div>';

  const destList = dests.filter(d => d.name !== selectedSource);

  if (destList.length === 0) {
    destsEl.innerHTML += '<div class="pb-empty">No destination devices</div>';
  } else {
    destsEl.innerHTML += destList.map(d => {
      const isConnected = activeSet.has(d.name);
      const chLabel = d.midi_channel ? `ch ${d.midi_channel}` : 'all ch';

      let cls = 'pb-box';
      if (isConnected)          cls += ' pb-box-connected';
      if (canTap && isConnected)  cls += ' pb-box-will-disconnect';
      if (canTap && !isConnected) cls += ' pb-box-will-connect';

      const onclick = canTap
        ? `onclick="toggleRoutePatchbay('${esc(d.name)}',${isConnected})"`
        : '';

      return `
        <div id="dst_${deviceId(d.name)}" class="${cls}" ${onclick}>
          <div class="pb-box-label">${isConnected ? '&#10003; CONNECTED' : 'DEST'}</div>
          <div class="pb-box-name">${esc(d.name)}</div>
          <div class="pb-box-meta">${chLabel} &middot; ${esc(d.device_type)}</div>
          ${isConnected && selectedSource
            ? `<button class="btn btn-sm" style="margin-top:10px;"
                onclick="event.stopPropagation(); editRouteFilter(null,'${esc(selectedSource)}','${esc(d.name)}')">
                Filter / Ch</button>`
            : ''}
        </div>`;
    }).join('');
  }

  // Update hint
  const hint = document.getElementById('routing-hint');
  if (selectedSource) {
    const exNote = exclusive ? ' — exclusive (replaces current)' : '';
    hint.textContent = `${selectedSource} selected${exNote} — tap a destination`;
    hint.style.color = 'var(--accent)';
  } else {
    hint.textContent = routingMode === 'perform'
      ? 'Tap a keyboard or controller to select it'
      : 'Tap any source device to select it';
    hint.style.color = '';
  }

  // Draw SVG connection lines after layout settles
  requestAnimationFrame(drawConnections);
}

function drawConnections() {
  const svg = document.getElementById('pb-lines');
  const canvas = document.getElementById('patchbay-canvas');
  if (!svg || !canvas) return;

  const cr = canvas.getBoundingClientRect();

  svg.innerHTML = `<defs>
    <marker id="arr"     markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0,8 3,0 6" fill="#0f9b8e"/></marker>
    <marker id="arr-sel" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0,8 3,0 6" fill="#12c4b3"/></marker>
    <marker id="arr-off" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0,8 3,0 6" fill="#5a6577"/></marker>
  </defs>`;

  routes.forEach(route => {
    const srcEl = document.getElementById('src_' + deviceId(route.from));
    const dstEl = document.getElementById('dst_' + deviceId(route.to));
    if (!srcEl || !dstEl) return;

    const sr = srcEl.getBoundingClientRect();
    const dr = dstEl.getBoundingClientRect();

    const x1 = sr.right  - cr.left;
    const y1 = sr.top    + sr.height / 2 - cr.top;
    const x2 = dr.left   - cr.left;
    const y2 = dr.top    + dr.height / 2 - cr.top;
    const dx = Math.max(48, Math.abs(x2 - x1) * 0.42);

    const isSel = route.from === selectedSource;
    const isOff = route.enabled === false;

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M ${x1} ${y1} C ${x1+dx} ${y1} ${x2-dx} ${y2} ${x2} ${y2}`);
    path.setAttribute('fill', 'none');

    if (isOff) {
      path.setAttribute('stroke', '#5a6577');
      path.setAttribute('stroke-width', '1.5');
      path.setAttribute('stroke-dasharray', '6,4');
      path.setAttribute('opacity', '0.35');
      path.setAttribute('marker-end', 'url(#arr-off)');
    } else if (isSel) {
      path.setAttribute('stroke', '#12c4b3');
      path.setAttribute('stroke-width', '2.5');
      path.setAttribute('opacity', '1');
      path.setAttribute('marker-end', 'url(#arr-sel)');
    } else {
      path.setAttribute('stroke', '#0f9b8e');
      path.setAttribute('stroke-width', '1.5');
      path.setAttribute('opacity', '0.45');
      path.setAttribute('marker-end', 'url(#arr)');
    }

    svg.appendChild(path);
  });
}

function selectSource(name) {
  selectedSource = (selectedSource === name) ? null : name;
  renderPatchbay();
}

async function toggleRoutePatchbay(to, isConnected) {
  if (!selectedSource) return;
  const exclusive = document.getElementById('exclusive-mode')?.checked;

  if (isConnected) {
    await api('/routes', { method: 'DELETE', body: { from: selectedSource, to } });
  } else {
    if (exclusive) {
      // Remove all existing routes from this source before adding the new one
      const existing = routes.filter(r => r.from === selectedSource).map(r => r.to);
      for (const dst of existing) {
        await api('/routes', { method: 'DELETE', body: { from: selectedSource, to: dst } });
      }
    }
    await api('/routes', { method: 'POST', body: { from: selectedSource, to, filter: {} } });
  }
  await loadRouting();
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
  selectedSource = null;
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
  monitorInterval = setInterval(refreshMonitor, 500);
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

let _performanceModeActive = false;

function _updatePerfBtn(active) {
  _performanceModeActive = active;
  const btn = document.getElementById('perf-mode-btn');
  if (btn) {
    if (active) {
      btn.textContent = 'Disable Performance Mode';
      btn.style.background = 'var(--error, #f44336)';
    } else {
      btn.textContent = 'Enable Performance Mode';
      btn.style.background = '';
    }
  }
  // Show/hide nav items that are noisy in performance mode
  document.querySelectorAll('.perf-hide').forEach(el => {
    el.style.display = active ? 'none' : '';
  });
  // If currently on a hidden page, go to dashboard
  if (active && ['monitor', 'player', 'logs'].includes(currentPage)) {
    navigateTo('dashboard');
  }
}

async function togglePerformanceMode() {
  const endpoint = _performanceModeActive ? '/performance/disable' : '/performance/enable';
  const result = await api(endpoint, { method: 'POST' });
  if (result.ok) {
    _updatePerfBtn(!_performanceModeActive);
  }
}

async function loadSettings() {
  const [data, devData, netData, rtpData] = await Promise.all([
    api('/settings'),
    api('/devices'),
    api('/network'),
    api('/rtpmidi'),
  ]);

  document.getElementById('setting-platform').value = data.platform;
  document.getElementById('setting-mode').value = data.mode;
  document.getElementById('setting-preset').value = data.preset || '(none)';

  _updatePerfBtn(!!data.performance_mode);

  // Populate clock source dropdown
  const select = document.getElementById('setting-clock-source');
  select.innerHTML = '<option value="">None</option>';
  devData.devices.forEach(d => {
    const selected = d.name === data.clock_source ? 'selected' : '';
    select.innerHTML += `<option value="${esc(d.name)}" ${selected}>${esc(d.name)}</option>`;
  });

  // Populate connect / WiFi section
  document.getElementById('connect-ssid').textContent  = netData.ssid;
  document.getElementById('connect-pass').textContent  = netData.password;
  document.getElementById('connect-url').textContent   = netData.url;
  document.getElementById('connect-wifi-text').textContent = netData.ssid;
  document.getElementById('connect-url-text').textContent  = netData.url;

  // Pre-fill the WiFi edit form with current SSID (leave password blank)
  document.getElementById('wifi-ssid-input').value = netData.ssid;
  document.getElementById('wifi-pass-input').value = '';
  document.getElementById('wifi-save-msg').textContent = '';

  // Software update status
  loadUpdateStatus();

  // RTP-MIDI status
  const badge = document.getElementById('rtpmidi-badge');
  const sessEl = document.getElementById('rtpmidi-sessions');
  if (badge) {
    badge.textContent = rtpData.enabled ? 'RUNNING' : 'DISABLED';
    badge.style.background = rtpData.enabled ? 'var(--success, #4caf50)' : 'var(--text-muted)';
  }
  if (sessEl) {
    if (!rtpData.enabled) {
      sessEl.textContent = 'Server not running (ports 5004/5005).';
    } else if (!rtpData.sessions || rtpData.sessions.length === 0) {
      sessEl.innerHTML = `Listening on ports ${rtpData.port}/${(rtpData.port||5004)+1} — no clients connected.<br>
        <span style="color:var(--text-muted);">Open Audio MIDI Setup on Mac → Network → connect to "MIDI Box".</span>`;
    } else {
      sessEl.innerHTML = rtpData.sessions.map(s =>
        `<div style="padding:2px 0;">&#9679; ${esc(s.name)} (${esc(s.address)})
         ${s.connected ? ' <span style="color:var(--success,#4caf50);">connected</span>'
                       : ' <span style="color:var(--text-muted);">handshaking</span>'}</div>`
      ).join('');
    }
  }
}

async function saveWifi(e) {
  e.preventDefault();
  const ssid     = document.getElementById('wifi-ssid-input').value.trim();
  const password = document.getElementById('wifi-pass-input').value;
  const msg      = document.getElementById('wifi-save-msg');

  msg.textContent = 'Saving…';
  msg.style.color = 'var(--text-muted)';

  const result = await api('/network', { method: 'POST', body: { ssid, password } });
  if (result.ok) {
    loadSettings();  // refresh QR codes and displayed credentials
    if (result.live) {
      _wifiRestartCountdown(ssid, password, msg);
    } else {
      msg.textContent = 'Saved — restart Pi to apply.';
      msg.style.color = 'var(--success, #4caf50)';
    }
  } else {
    msg.textContent = result.error || 'Failed to save.';
    msg.style.color = 'var(--error, #f44336)';
  }
  return false;
}

function _wifiRestartCountdown(ssid, password, msg) {
  // Server delays the hostapd restart by 2s so the HTTP response arrives first.
  // Count down so the user knows to reconnect before the network drops.
  let secs = 2;
  function tick() {
    if (secs > 0) {
      msg.textContent = `WiFi restarting in ${secs}s…`;
      msg.style.color = 'var(--text-muted)';
      secs--;
      setTimeout(tick, 1000);
    } else {
      msg.innerHTML = `Reconnect to: <strong>${ssid}</strong> &nbsp; pw: <strong>${password}</strong>`;
      msg.style.color = 'var(--success, #4caf50)';
    }
  }
  tick();
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

// --- Clip Launcher ---

let launcherInterval = null;
let launcherData = null;
let pendingClipAssign = null; // {layerId, slot}

async function loadLauncher() {
  const data = await api('/launcher');
  launcherData = data;

  // Update clock controls
  updateClockControls(data.clock);

  // Render layer grid
  renderLauncherGrid(data.layers, data.files);

  // Start polling
  if (launcherInterval) clearInterval(launcherInterval);
  launcherInterval = setInterval(pollLauncher, 500);
}

async function pollLauncher() {
  if (currentPage !== 'launcher') {
    clearInterval(launcherInterval);
    launcherInterval = null;
    return;
  }
  const poll = await api('/launcher/poll');
  updateBeatDisplay(poll);
  updateClipStates(poll.layers);
}

function updateClockControls(clock) {
  document.getElementById('launcher-bpm').value = clock.bpm;
  document.getElementById('launcher-quantum').value = clock.quantum;
  document.getElementById('launcher-timesig').value = clock.beats_per_bar;

  document.getElementById('clock-int').classList.toggle('active', clock.mode === 'internal');
  document.getElementById('clock-ext').classList.toggle('active', clock.mode === 'external');
}

function updateBeatDisplay(poll) {
  const barEl = document.querySelector('.beat-bar');
  if (barEl) barEl.textContent = `BAR ${poll.bar + 1}`;

  const dots = document.querySelectorAll('#beat-dots .beat-dot');
  dots.forEach((dot, i) => {
    dot.classList.toggle('active', poll.running && i === poll.beat);
  });

  // Update transport button states
  document.getElementById('transport-start').disabled = poll.running;
  document.getElementById('transport-stop').disabled = !poll.running;
}

function updateClipStates(layerPolls) {
  if (!layerPolls) return;
  layerPolls.forEach(lp => {
    lp.clip_states.forEach((state, slot) => {
      const el = document.getElementById(`clip-${lp.id}-${slot}`);
      if (!el) return;
      // Remove all state classes
      el.classList.remove('clip-playing', 'clip-queued', 'clip-stopping', 'clip-stopped', 'clip-empty');
      el.classList.add('clip-' + state);
    });
  });
}

function renderLauncherGrid(layers, files) {
  const grid = document.getElementById('launcher-grid');
  if (!layers || layers.length === 0) {
    grid.innerHTML = '<div class="card" style="text-align:center; padding:40px; color:var(--text-muted);">No layers yet. Click "+ Add Layer" to create one.</div>';
    return;
  }

  grid.innerHTML = layers.map(layer => {
    const clips = layer.clips.map(c => {
      const stateClass = 'clip-' + c.state;
      const label = c.state === 'empty'
        ? '+'
        : (c.name || c.filename || '?');
      const onclick = c.state === 'empty'
        ? `onclick="openClipAssignModal(${layer.id}, ${c.slot})"`
        : `onclick="launchClip(${layer.id}, ${c.slot})"`;
      const removeBtn = c.state !== 'empty'
        ? `<span class="clip-remove" onclick="event.stopPropagation(); removeClip(${layer.id}, ${c.slot})">&times;</span>`
        : '';
      return `<div id="clip-${layer.id}-${c.slot}" class="clip-slot ${stateClass}" ${onclick}>
        <span class="clip-label">${esc(label)}</span>
        ${removeBtn}
      </div>`;
    }).join('');

    const chLabel = layer.midi_channel ? `ch ${layer.midi_channel}` : 'all ch';

    return `
      <div class="card layer-row" style="margin-top:8px;">
        <div class="layer-header">
          <div class="layer-name">${esc(layer.name || 'Layer ' + layer.id)}</div>
          <div class="layer-dest">&rarr; ${esc(layer.destination)}</div>
          <div class="layer-ch">${chLabel}</div>
          <button class="btn btn-sm" onclick="stopLayerBtn(${layer.id})">Stop</button>
          <button class="btn btn-sm btn-danger" onclick="removeLayer(${layer.id})">Remove</button>
        </div>
        <div class="clip-row">${clips}</div>
      </div>`;
  }).join('');
}

// Clock controls
async function setClockMode(mode) {
  await api('/launcher/clock', { method: 'POST', body: { mode } });
  document.getElementById('clock-int').classList.toggle('active', mode === 'internal');
  document.getElementById('clock-ext').classList.toggle('active', mode === 'external');
}

async function adjustBpm(delta) {
  const input = document.getElementById('launcher-bpm');
  const bpm = Math.max(20, Math.min(300, parseFloat(input.value) + delta));
  input.value = bpm;
  await api('/launcher/clock', { method: 'POST', body: { bpm } });
}

async function setBpm(val) {
  await api('/launcher/clock', { method: 'POST', body: { bpm: parseFloat(val) } });
}

async function setQuantum(val) {
  await api('/launcher/clock', { method: 'POST', body: { quantum: val } });
}

async function setTimeSig(val) {
  await api('/launcher/clock', { method: 'POST', body: { beats_per_bar: parseInt(val) } });
  // Update beat dots
  const dots = document.getElementById('beat-dots');
  if (dots) {
    dots.innerHTML = Array.from({length: parseInt(val)}, () => '<span class="beat-dot"></span>').join('');
  }
}

async function transportStart() {
  await api('/launcher/transport/start', { method: 'POST' });
}

async function transportStop() {
  await api('/launcher/transport/stop', { method: 'POST' });
}

// Clip actions
async function launchClip(layerId, slot) {
  await api(`/launcher/layers/${layerId}/clips/${slot}/launch`, { method: 'POST' });
}

async function removeClip(layerId, slot) {
  await api(`/launcher/layers/${layerId}/clips/${slot}`, { method: 'DELETE' });
  loadLauncher();
}

async function stopLayerBtn(layerId) {
  await api(`/launcher/layers/${layerId}/stop`, { method: 'POST' });
}

async function removeLayer(layerId) {
  if (!confirm('Remove this layer?')) return;
  await api(`/launcher/layers/${layerId}`, { method: 'DELETE' });
  loadLauncher();
}

async function launcherStopAll() {
  await api('/launcher/stop_all', { method: 'POST' });
}

// Clip assign modal
function openClipAssignModal(layerId, slot) {
  pendingClipAssign = { layerId, slot };
  const layer = launcherData?.layers?.find(l => l.id === layerId);
  document.getElementById('clip-assign-info').textContent =
    `Layer: ${layer?.name || layerId} — Slot ${slot + 1}`;

  const fileSelect = document.getElementById('clip-assign-file');
  const files = launcherData?.files || [];
  fileSelect.innerHTML = files.length === 0
    ? '<option value="">No MIDI files — upload one first</option>'
    : files.map(f => `<option value="${esc(f.name)}">${esc(f.name)} (${f.duration}s)</option>`).join('');

  document.getElementById('clip-assign-name').value = '';
  document.getElementById('clip-assign-loop').checked = true;
  document.getElementById('clip-assign-modal').classList.add('active');
}

function closeClipAssignModal() {
  document.getElementById('clip-assign-modal').classList.remove('active');
  pendingClipAssign = null;
}

async function confirmClipAssign() {
  if (!pendingClipAssign) return;
  const { layerId, slot } = pendingClipAssign;
  const filename = document.getElementById('clip-assign-file').value;
  if (!filename) return;

  const name = document.getElementById('clip-assign-name').value;
  const loop = document.getElementById('clip-assign-loop').checked;

  await api(`/launcher/layers/${layerId}/clips/${slot}`, {
    method: 'POST',
    body: { filename, name, loop },
  });

  closeClipAssignModal();
  loadLauncher();
}

// Add layer modal
async function addLayerModal() {
  const devData = await api('/devices');
  const outputDevices = devData.devices.filter(d => d.direction === 'both' || d.direction === 'out');

  const destSelect = document.getElementById('layer-add-dest');
  destSelect.innerHTML = outputDevices.map(d =>
    `<option value="${esc(d.name)}">${esc(d.name)}</option>`
  ).join('');

  document.getElementById('layer-add-name').value = '';
  document.getElementById('layer-add-ch').value = 0;
  document.getElementById('add-layer-modal').classList.add('active');
}

function closeAddLayerModal() {
  document.getElementById('add-layer-modal').classList.remove('active');
}

async function confirmAddLayer() {
  const name = document.getElementById('layer-add-name').value;
  const destination = document.getElementById('layer-add-dest').value;
  const midi_channel = parseInt(document.getElementById('layer-add-ch').value) || 0;

  if (!destination) return;

  await api('/launcher/layers', {
    method: 'POST',
    body: { name: name || destination, destination, midi_channel },
  });

  closeAddLayerModal();
  loadLauncher();
}

async function uploadLauncherFile(input) {
  const file = input.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  await fetch('/api/launcher/upload', { method: 'POST', body: formData });
  input.value = '';
  loadLauncher();
}

// --- MIDI Player ---

let playerInterval = null;

async function loadPlayer() {
  const [playerData, devData] = await Promise.all([
    api('/player'),
    api('/devices'),
  ]);

  // Populate file select
  const fileSelect = document.getElementById('player-file');
  fileSelect.innerHTML = playerData.files.length === 0
    ? '<option value="">No MIDI files — upload one</option>'
    : playerData.files.map(f =>
        `<option value="${esc(f.name)}">${esc(f.name)} (${f.duration}s, ${f.tracks} tracks)</option>`
      ).join('');

  // Populate destination select (output devices)
  const destSelect = document.getElementById('player-dest');
  const outputDevices = devData.devices.filter(d => d.direction === 'both' || d.direction === 'out');
  destSelect.innerHTML = outputDevices.map(d =>
    `<option value="${esc(d.name)}">${esc(d.name)}</option>`
  ).join('');

  // Restore current status
  updatePlayerUI(playerData.status);

  // Render file list
  renderMidiFileList(playerData.files);

  // Start polling player status
  if (playerInterval) clearInterval(playerInterval);
  playerInterval = setInterval(pollPlayerStatus, 500);
}

async function pollPlayerStatus() {
  if (currentPage !== 'player') {
    clearInterval(playerInterval);
    playerInterval = null;
    return;
  }
  const data = await api('/player');
  updatePlayerUI(data.status);
}

function updatePlayerUI(status) {
  const playBtn = document.getElementById('player-play-btn');
  const pauseBtn = document.getElementById('player-pause-btn');
  const stopBtn = document.getElementById('player-stop-btn');
  const statusEl = document.getElementById('player-status');

  if (status.playing) {
    playBtn.disabled = true;
    pauseBtn.disabled = false;
    pauseBtn.textContent = 'Pause';
    stopBtn.disabled = false;
    const pos = status.position || 0;
    const dur = status.duration || 0;
    statusEl.textContent = `Playing: ${status.file} → ${status.destination} (${pos.toFixed(1)}s / ${dur.toFixed(1)}s)${status.loop ? ' [LOOP]' : ''}`;
    statusEl.style.color = 'var(--accent)';
  } else if (status.paused) {
    playBtn.disabled = true;
    pauseBtn.disabled = false;
    pauseBtn.textContent = 'Resume';
    stopBtn.disabled = false;
    statusEl.textContent = `Paused: ${status.file}`;
    statusEl.style.color = 'var(--warning, #f0a030)';
  } else {
    playBtn.disabled = false;
    pauseBtn.disabled = true;
    pauseBtn.textContent = 'Pause';
    stopBtn.disabled = true;
    statusEl.textContent = 'Stopped';
    statusEl.style.color = 'var(--text-muted)';
  }
}

async function playerPlay() {
  const file = document.getElementById('player-file').value;
  const dest = document.getElementById('player-dest').value;
  const loop = document.getElementById('player-loop').checked;
  const tempo = parseInt(document.getElementById('player-tempo').value) / 100;

  if (!file || !dest) return;

  await api('/player/play', {
    method: 'POST',
    body: { file, destination: dest, loop, tempo },
  });
}

async function playerPause() {
  const data = await api('/player');
  if (data.status.paused) {
    await api('/player/resume', { method: 'POST' });
  } else {
    await api('/player/pause', { method: 'POST' });
  }
}

async function playerStop() {
  await api('/player/stop', { method: 'POST' });
}

async function uploadMidiFile(input) {
  const file = input.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  const resp = await fetch('/api/player/upload', { method: 'POST', body: formData });
  const data = await resp.json();

  if (data.ok) {
    loadPlayer();
  } else {
    alert('Upload failed: ' + (data.error || 'unknown error'));
  }
  input.value = '';
}

async function deleteMidiFile(name) {
  if (!confirm(`Delete "${name}"?`)) return;
  await api('/player/delete', { method: 'POST', body: { file: name } });
  loadPlayer();
}

function renderMidiFileList(files) {
  const list = document.getElementById('midi-file-list');
  if (files.length === 0) {
    list.innerHTML = '<li class="preset-item" style="color:var(--text-muted);">No MIDI files uploaded. Click "Upload .mid" to add one.</li>';
    return;
  }

  list.innerHTML = files.map(f => `
    <li class="preset-item">
      <div>
        <div class="preset-name">${esc(f.name)}</div>
        <div class="preset-desc">${f.duration}s &middot; ${f.tracks} track${f.tracks !== 1 ? 's' : ''}</div>
      </div>
      <div class="btn-group">
        <button class="btn btn-sm btn-danger" onclick="deleteMidiFile('${esc(f.name)}')">Delete</button>
      </div>
    </li>
  `).join('');
}

// --- Device Config Modal ---

let pendingDeviceName = null;

function openDeviceModal(name) {
  pendingDeviceName = name;
  const dev = devices.find(d => d.name === name);
  if (!dev) return;

  document.getElementById('device-modal-name').textContent = name;
  document.getElementById('device-direction').value = dev.direction || 'both';
  document.getElementById('device-type').value = dev.device_type || 'unknown';
  document.getElementById('device-channel').value = dev.midi_channel || 0;
  document.getElementById('device-modal').classList.add('active');
}

function closeDeviceModal() {
  document.getElementById('device-modal').classList.remove('active');
  pendingDeviceName = null;
}

async function applyDeviceConfig() {
  if (!pendingDeviceName) return;

  const direction = document.getElementById('device-direction').value;
  const device_type = document.getElementById('device-type').value;
  const midi_channel = parseInt(document.getElementById('device-channel').value) || 0;

  await api(`/devices/${encodeURIComponent(pendingDeviceName)}/config`, {
    method: 'POST',
    body: { direction, device_type, midi_channel },
  });

  closeDeviceModal();
  loadDashboard();
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

// --- System page ---

let systemInterval = null;

function startSystem() {
  refreshSystem();
  if (systemInterval) clearInterval(systemInterval);
  systemInterval = setInterval(() => {
    if (currentPage !== 'system') { clearInterval(systemInterval); systemInterval = null; return; }
    refreshSystem();
  }, 3000);
}

async function refreshSystem() {
  let data;
  try { data = await api('/system'); } catch (_) { return; }

  // CPU bar
  setBar('sys-cpu-bar', data.cpu_percent);
  document.getElementById('sys-cpu-val').textContent = data.cpu_percent + '%';
  document.getElementById('sys-cpu-bar').style.background =
    data.cpu_percent > 85 ? 'var(--danger)' : data.cpu_percent > 60 ? 'var(--warning)' : 'var(--accent)';

  // RAM bar
  setBar('sys-ram-bar', data.ram_percent);
  document.getElementById('sys-ram-val').textContent =
    data.ram_used_mb + ' MB / ' + data.ram_total_mb + ' MB (' + data.ram_percent + '%)';

  // Disk bar
  setBar('sys-disk-bar', data.disk_percent);
  document.getElementById('sys-disk-val').textContent =
    data.disk_used_gb + ' GB / ' + data.disk_total_gb + ' GB (' + data.disk_percent + '%)';

  // Temperature
  const tempEl = document.getElementById('sys-temp');
  if (data.cpu_temp_c !== null && data.cpu_temp_c !== undefined) {
    tempEl.textContent = data.cpu_temp_c + ' °C';
    tempEl.style.color = data.cpu_temp_c > 75 ? 'var(--danger)' : data.cpu_temp_c > 60 ? 'var(--warning)' : 'var(--success)';
  } else {
    tempEl.textContent = 'N/A';
    tempEl.style.color = 'var(--text-muted)';
  }

  // Uptime
  document.getElementById('sys-uptime').textContent = fmtUptime(data.uptime_seconds);

  // Platform
  document.getElementById('sys-platform').textContent = data.platform || '—';
}

function setBar(id, pct) {
  const el = document.getElementById(id);
  if (el) el.style.width = Math.min(100, Math.max(0, pct)) + '%';
}

function fmtUptime(seconds) {
  if (!seconds) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (d) parts.push(d + 'd');
  if (h) parts.push(h + 'h');
  parts.push(m + 'm');
  return parts.join(' ');
}

// --- Quick Recorder ---

let recInterval     = null;
let recElapsedTimer = null;
let recState        = 'idle';
let recElapsedSecs  = 0;

async function loadRecorder() {
  const data = await api('/recorder');
  _applyRecorderState(data);
  loadRecordings();
  if (recInterval) clearInterval(recInterval);
  recInterval = setInterval(pollRecorder, 400);
}

async function pollRecorder() {
  if (currentPage !== 'recorder') {
    clearInterval(recInterval);
    recInterval = null;
    _clearRecElapsedTimer();
    return;
  }
  const data = await api('/recorder');
  _applyRecorderState(data);
}

function _applyRecorderState(data) {
  if (!data || !data.state) return;
  const prev  = recState;
  recState    = data.state;

  // Elapsed timer management
  if (recState === 'recording' && prev !== 'recording') {
    recElapsedSecs = 0;
    _clearRecElapsedTimer();
    recElapsedTimer = setInterval(() => {
      recElapsedSecs++;
      const el = document.getElementById('rec-elapsed');
      if (el) el.textContent = _fmtSecs(recElapsedSecs);
    }, 1000);
  } else if (recState !== 'recording') {
    _clearRecElapsedTimer();
    const el = document.getElementById('rec-elapsed');
    if (el) el.textContent = data.length > 0 ? _fmtSecs(data.length) : '';
  }

  // Badge
  const badge = document.getElementById('rec-status-badge');
  if (badge) {
    const labels = {idle:'IDLE', count_in:'COUNT IN', recording:'● REC', playing:'▶ PLAYING', stopped:'STOPPED'};
    badge.textContent = labels[recState] || recState.toUpperCase();
    badge.className   = 'rec-state-badge ' + recState;
  }

  // Toggle button
  const toggleBtn = document.getElementById('rec-toggle-btn');
  if (toggleBtn) {
    if (recState === 'recording') {
      toggleBtn.textContent = '⏹ Stop Recording';
      toggleBtn.className = 'btn btn-danger';
    } else if (recState === 'count_in') {
      toggleBtn.textContent = '⏹ Cancel';
      toggleBtn.className = 'btn btn-danger';
    } else {
      toggleBtn.textContent = '⏺ RECORD';
      toggleBtn.className = 'btn btn-accent';
    }
  }

  // Other buttons
  const stopBtn  = document.getElementById('rec-stop-btn');
  const playBtn  = document.getElementById('rec-play-btn');
  const clearBtn = document.getElementById('rec-clear-btn');
  if (stopBtn)  stopBtn.disabled  = recState === 'idle';
  if (playBtn)  playBtn.disabled  = recState !== 'stopped' || !data.event_count;
  if (clearBtn) clearBtn.disabled = recState === 'idle';

  // Auto-play toggle
  const apToggle = document.getElementById('rec-auto-play');
  if (apToggle && apToggle.checked !== !!data.auto_play) {
    apToggle.checked = !!data.auto_play;
  }

  // Stats
  const stats = document.getElementById('rec-stats');
  if (stats) {
    if (data.event_count > 0) {
      stats.textContent = `${data.event_count} events  ·  loop: ${data.length.toFixed(2)}s`;
    } else {
      stats.textContent = '';
    }
  }

  // Save card visibility
  const saveCard = document.getElementById('rec-save-card');
  if (saveCard) {
    saveCard.style.display = (recState === 'stopped' || recState === 'playing') && data.event_count
      ? '' : 'none';
  }

  // Note feed
  if (data.recent_events) {
    renderNoteFeed(data.recent_events);
  }

  // Clock bar
  _applyRecClockState(data);
}

function _applyRecClockState(data) {
  // Clock source buttons
  const sources = ['standalone', 'launcher', 'external'];
  const ids = ['rec-clock-standalone', 'rec-clock-launcher', 'rec-clock-ext'];
  sources.forEach((s, i) => {
    const btn = document.getElementById(ids[i]);
    if (btn) btn.className = 'tab-btn' + (data.clock_source === s ? ' active' : '');
  });

  // BPM — disabled when synced to launcher
  const bpmInput = document.getElementById('rec-bpm');
  if (bpmInput) {
    bpmInput.value = Math.round(data.bpm || 120);
    bpmInput.disabled = data.clock_source === 'launcher';
  }

  // Quantize selector
  const qSel = document.getElementById('rec-quantize');
  if (qSel && qSel.value !== data.quantize) {
    qSel.value = data.quantize || 'free';
  }

  // Beat display
  const barLabel = document.getElementById('rec-bar-label');
  if (barLabel) barLabel.textContent = 'BAR ' + ((data.bar || 0) + 1);
  const dotsEl = document.getElementById('rec-beat-dots');
  if (dotsEl) {
    const bpb = data.beats_per_bar || 4;
    const dots = dotsEl.querySelectorAll('.beat-dot');
    // Adjust dot count
    while (dots.length < bpb) {
      dotsEl.appendChild(Object.assign(document.createElement('span'), {className:'beat-dot'}));
    }
    const allDots = dotsEl.querySelectorAll('.beat-dot');
    allDots.forEach((d, i) => {
      d.style.display = i < bpb ? '' : 'none';
      d.classList.toggle('active', i === (data.beat || 0) && data.transport_running);
    });
    // Count-in pulse
    if (recState === 'count_in') {
      allDots.forEach(d => d.classList.add('count-in-pulse'));
    } else {
      allDots.forEach(d => d.classList.remove('count-in-pulse'));
    }
  }
}

function _clearRecElapsedTimer() {
  if (recElapsedTimer) {
    clearInterval(recElapsedTimer);
    recElapsedTimer = null;
  }
}

function _fmtSecs(s) {
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed ? (s % 60).toFixed(0).padStart(2, '0') : String(Math.floor(s % 60)).padStart(2, '0');
  return `${m}:${sec}`;
}

function renderNoteFeed(events) {
  const el = document.getElementById('rec-note-feed');
  if (!el) return;
  const rows = events.filter(e => e.type === 'note_on' || e.type === 'note_off');
  if (!rows.length) return;
  el.innerHTML = rows.map(e => {
    const t   = e.offset.toFixed(2).padStart(6, ' ');
    const src = esc(e.source || '');
    const note = esc(e.note || '');
    const vel  = e.velocity !== undefined ? e.velocity : '';
    const ch   = e.channel  !== undefined ? 'ch' + e.channel : '';
    const dim  = e.type === 'note_off' ? 'opacity:0.45;' : '';
    return `<div class="rec-note-row" style="${dim}">
      <span class="r-time">${t}s</span>
      <span class="r-src">${src}</span>
      <span class="r-note">${note}</span>
      <span class="r-vel">${vel !== '' ? 'v:' + vel : ''}</span>
      <span class="r-ch">${ch}</span>
    </div>`;
  }).join('');
  el.scrollTop = el.scrollHeight;
}

async function recToggle()               { await api('/recorder/toggle',    { method: 'POST' }); }
async function recPlay()                 { await api('/recorder/play',      { method: 'POST' }); }
async function recStop()                 { await api('/recorder/stop',      { method: 'POST' }); }
async function recClear()                { await api('/recorder/clear',     { method: 'POST' }); }
async function recSetAutoPlay(val)       { await api('/recorder/auto_play', { method: 'POST', body: { value: val } }); }

async function recSetClockSource(source) { await api('/recorder/clock', { method: 'POST', body: { source } }); }
async function recSetBpm(bpm)            { await api('/recorder/clock', { method: 'POST', body: { bpm: parseFloat(bpm) } }); }
async function recSetQuantize(q)         { await api('/recorder/clock', { method: 'POST', body: { quantize: q } }); }
function recAdjustBpm(delta) {
  const input = document.getElementById('rec-bpm');
  if (!input || input.disabled) return;
  const bpm = Math.max(20, Math.min(300, parseFloat(input.value) + delta));
  input.value = bpm;
  recSetBpm(bpm);
}

async function recSave() {
  const name = document.getElementById('rec-save-name')?.value.trim() || null;
  const msg  = document.getElementById('rec-save-msg');
  if (msg) { msg.textContent = 'Saving…'; msg.style.color = 'var(--text-muted)'; }
  const result = await api('/recorder/save', { method: 'POST', body: { name } });
  if (result.ok) {
    if (msg) { msg.textContent = `Saved: ${result.name}.mid`; msg.style.color = 'var(--success,#2ecc71)'; }
    loadRecordings();
  } else {
    if (msg) { msg.textContent = result.error || 'Save failed'; msg.style.color = 'var(--error,#f44336)'; }
  }
}

async function loadRecordings() {
  const result = await api('/recorder/recordings');
  const list = document.getElementById('rec-recordings-list');
  if (!list) return;
  const recordings = result.recordings || [];
  if (!recordings.length) {
    list.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">No recordings yet.</div>';
    return;
  }
  list.innerHTML = recordings.map(r => `
    <div class="rec-recording-row">
      <div class="rec-recording-info">
        <div class="rec-recording-name">${esc(r.name)}</div>
        <div class="rec-recording-meta">${r.created_at || ''} &nbsp;·&nbsp; ${r.length_sec || 0}s &nbsp;·&nbsp; ${r.event_count || 0} events</div>
      </div>
      <div class="rec-recording-actions">
        <a class="btn btn-sm btn-accent" href="/api/recorder/recordings/${encodeURIComponent(r.name)}"
           download="${esc(r.name)}.mid">&#8659; .mid</a>
        <button class="btn btn-sm btn-danger" onclick="recDelete('${esc(r.name)}')">&#10005;</button>
      </div>
    </div>
  `).join('');
}

async function recDelete(name) {
  if (!confirm(`Delete recording "${name}"?`)) return;
  await api(`/recorder/recordings/${encodeURIComponent(name)}`, { method: 'DELETE' });
  loadRecordings();
}

// --- MIDI Looper ---

let loopInterval = null;

async function loadLooper() {
  const data = await api('/looper');
  _applyLooperState(data);
  if (loopInterval) clearInterval(loopInterval);
  loopInterval = setInterval(pollLooper, 400);
}

async function pollLooper() {
  if (currentPage !== 'looper') {
    clearInterval(loopInterval);
    loopInterval = null;
    return;
  }
  const data = await api('/looper');
  _applyLooperState(data);
}

function _applyLooperState(data) {
  if (!data) return;

  // Clock bar
  _applyLoopClockState(data);

  // Slots
  const container = document.getElementById('looper-slots');
  if (!container) return;

  const slots = data.slots || [];
  if (!container.children.length || container.children.length !== slots.length) {
    _renderLooperSlots(container, slots);
  } else {
    _updateLooperSlots(slots);
  }
}

function _applyLoopClockState(data) {
  const sources = ['standalone', 'launcher', 'external'];
  const ids = ['loop-clock-standalone', 'loop-clock-launcher', 'loop-clock-ext'];
  sources.forEach((s, i) => {
    const btn = document.getElementById(ids[i]);
    if (btn) btn.className = 'tab-btn' + (data.clock_source === s ? ' active' : '');
  });

  const bpmInput = document.getElementById('loop-bpm');
  if (bpmInput) {
    bpmInput.value = Math.round(data.bpm || 120);
    bpmInput.disabled = data.clock_source === 'launcher';
  }

  const qSel = document.getElementById('loop-quantize');
  if (qSel && qSel.value !== data.quantize) {
    qSel.value = data.quantize || 'free';
  }

  const barLabel = document.getElementById('loop-bar-label');
  if (barLabel) barLabel.textContent = 'BAR ' + ((data.bar || 0) + 1);
  const dotsEl = document.getElementById('loop-beat-dots');
  if (dotsEl) {
    const bpb = data.beats_per_bar || 4;
    const dots = dotsEl.querySelectorAll('.beat-dot');
    while (dots.length < bpb) {
      dotsEl.appendChild(Object.assign(document.createElement('span'), {className:'beat-dot'}));
    }
    const allDots = dotsEl.querySelectorAll('.beat-dot');
    allDots.forEach((d, i) => {
      d.style.display = i < bpb ? '' : 'none';
      d.classList.toggle('active', i === (data.beat || 0) && data.transport_running);
    });
  }
}

function _renderLooperSlots(container, slots) {
  container.innerHTML = slots.map(s => `
    <div class="card looper-slot" id="loop-slot-${s.slot_id}">
      <div class="card-header">
        <div style="display:flex;align-items:center;gap:10px;">
          <strong>Slot ${s.slot_id + 1}</strong>
          <span class="rec-state-badge ${s.state}" id="loop-badge-${s.slot_id}">${_loopStateLabel(s.state)}</span>
        </div>
        <span style="font-size:11px;color:var(--text-muted);" id="loop-info-${s.slot_id}">
          ${s.event_count} events · ${s.length}s
        </span>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px;">
        <select id="loop-src-${s.slot_id}" style="flex:1;min-width:120px;" onchange="loopConfigure(${s.slot_id})">
          <option value="">-- Source --</option>
        </select>
        <select id="loop-dst-${s.slot_id}" style="flex:1;min-width:120px;" onchange="loopConfigure(${s.slot_id})">
          <option value="">-- Destination --</option>
        </select>
      </div>
      <div class="btn-group" style="flex-wrap:wrap;gap:6px;">
        <button class="btn btn-accent" onclick="loopRecord(${s.slot_id})">&#9210; REC</button>
        <button class="btn" onclick="loopPlay(${s.slot_id})">&#9654; Play</button>
        <button class="btn" onclick="loopStop(${s.slot_id})">&#9632; Stop</button>
        <button class="btn btn-danger" onclick="loopClear(${s.slot_id})">&#10005; Clear</button>
      </div>
    </div>
  `).join('');
  // Populate device dropdowns
  _populateLooperDeviceDropdowns(slots);
}

async function _populateLooperDeviceDropdowns(slots) {
  const devData = await api('/devices');
  const devices = devData || [];
  slots.forEach(s => {
    const srcSel = document.getElementById(`loop-src-${s.slot_id}`);
    const dstSel = document.getElementById(`loop-dst-${s.slot_id}`);
    if (srcSel) {
      devices.forEach(d => {
        if (d.direction !== 'out') {
          const opt = new Option(d.name, d.name, false, d.name === s.source);
          srcSel.add(opt);
        }
      });
    }
    if (dstSel) {
      devices.forEach(d => {
        if (d.direction !== 'in') {
          const opt = new Option(d.name, d.name, false, d.name === s.destination);
          dstSel.add(opt);
        }
      });
    }
  });
}

function _updateLooperSlots(slots) {
  slots.forEach(s => {
    const badge = document.getElementById(`loop-badge-${s.slot_id}`);
    if (badge) {
      badge.textContent = _loopStateLabel(s.state);
      badge.className = 'rec-state-badge ' + s.state;
    }
    const info = document.getElementById(`loop-info-${s.slot_id}`);
    if (info) info.textContent = `${s.event_count} events · ${s.length}s`;
  });
}

function _loopStateLabel(state) {
  const labels = {empty:'EMPTY', count_in:'COUNT IN', recording:'● REC',
                  playing:'▶ LOOP', overdubbing:'● DUB', stopped:'STOPPED'};
  return labels[state] || state.toUpperCase();
}

async function loopRecord(slot)    { await api(`/looper/${slot}/record`,    { method: 'POST' }); }
async function loopPlay(slot)      { await api(`/looper/${slot}/play`,      { method: 'POST' }); }
async function loopStop(slot)      { await api(`/looper/${slot}/stop`,      { method: 'POST' }); }
async function loopClear(slot)     { await api(`/looper/${slot}/clear`,     { method: 'POST' }); }

async function loopConfigure(slot) {
  const src = document.getElementById(`loop-src-${slot}`)?.value || '';
  const dst = document.getElementById(`loop-dst-${slot}`)?.value || '';
  await api(`/looper/${slot}/configure`, { method: 'POST', body: { source: src, destination: dst } });
}

async function loopSetClockSource(source) { await api('/looper/clock', { method: 'POST', body: { source } }); }
async function loopSetBpm(bpm)            { await api('/looper/clock', { method: 'POST', body: { bpm: parseFloat(bpm) } }); }
async function loopSetQuantize(q)         { await api('/looper/clock', { method: 'POST', body: { quantize: q } }); }
function loopAdjustBpm(delta) {
  const input = document.getElementById('loop-bpm');
  if (!input || input.disabled) return;
  const bpm = Math.max(20, Math.min(300, parseFloat(input.value) + delta));
  input.value = bpm;
  loopSetBpm(bpm);
}

// --- MIDI Panic (silence all notes) ---

async function midiPanic() {
  const btn    = document.getElementById('panic-btn');
  const status = document.getElementById('panic-status');

  if (btn) { btn.disabled = true; btn.textContent = 'Silencing…'; }
  try {
    await api('/panic', { method: 'POST' });
  } catch (_) {}
  if (status) { status.textContent = 'All Notes Off'; status.style.color = 'var(--accent)'; }
  setTimeout(() => {
    if (btn)    { btn.textContent = '\u25A0 PANIC'; btn.disabled = false; }
    if (status) { status.textContent = ''; }
  }, 2000);
}

// --- Service restart ---

async function panicRestart() {
  const btn    = document.getElementById('panic-btn');
  const status = document.getElementById('panic-status');
  const sysStatus = document.getElementById('sys-restart-status');

  const setState = (text, color) => {
    if (btn)       { btn.textContent = text; btn.style.background = color; btn.disabled = true; }
    if (status)    { status.textContent = text; status.style.color = color; }
    if (sysStatus) { sysStatus.textContent = text; sysStatus.style.color = color; }
  };

  setState('Restarting…', 'var(--warning)');

  try {
    await fetch('/api/system/restart', { method: 'POST' });
  } catch (_) { /* expected — server dies */ }

  // Wait for server to go down, then poll until it comes back
  await new Promise(r => setTimeout(r, 3000));
  setState('Reconnecting…', 'var(--warning)');

  let attempts = 0;
  const poll = setInterval(async () => {
    attempts++;
    try {
      const r = await fetch('/api/settings');
      if (r.ok) {
        clearInterval(poll);
        setState('Back online!', 'var(--success)');
        setTimeout(() => {
          if (btn) { btn.textContent = '\u25A0 PANIC'; btn.style.background = ''; btn.disabled = false; }
          if (status) status.textContent = '';
          if (sysStatus) sysStatus.textContent = '';
          location.reload();
        }, 1200);
      }
    } catch (_) {
      if (attempts > 40) {  // 20s timeout
        clearInterval(poll);
        setState('Timeout — check Pi', 'var(--danger)');
        if (btn) btn.disabled = false;
      }
    }
  }, 500);
}

// --- Polling for activity updates (dashboard) ---

function startPolling() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    if (currentPage !== 'dashboard') return;
    // Use the lightweight /api/poll endpoint — only updates activity dots,
    // never re-renders the whole device list (that happens on page load only).
    try {
      const data = await api('/poll');
      updateDashboardActivity(data);
    } catch (_) { /* ignore transient failures */ }
  }, 2000);
}

// --- Software Update ---

let _updatePollTimer = null;

async function loadUpdateStatus() {
  try {
    const data = await api('/update/status');
    _renderUpdateStatus(data);
    if (data.update_status === 'running') {
      _startUpdateLogPolling();
    }
  } catch (_) {}
}

function _renderUpdateStatus(data) {
  const curEl    = document.getElementById('update-current-version');
  const latEl    = document.getElementById('update-latest-version');
  const badge    = document.getElementById('update-version-badge');
  const typeInfo = document.getElementById('update-type-info');
  const trigBtn  = document.getElementById('update-trigger-btn');
  const checkedEl= document.getElementById('update-last-checked');
  const errEl    = document.getElementById('update-error-msg');

  if (!curEl) return;

  curEl.value = data.current_version || '—';
  latEl.value = data.latest_version  || '—';
  if (checkedEl) {
    checkedEl.textContent = data.last_checked
      ? `Last checked: ${data.last_checked}` : '';
  }

  if (data.check_error) {
    if (badge) {
      badge.textContent = 'ERROR';
      badge.style.background = 'rgba(231,76,60,0.15)';
      badge.style.color = 'var(--danger)';
    }
    if (errEl) errEl.textContent = `Check failed: ${data.check_error}`;
  } else if (data.update_status === 'running') {
    if (badge) {
      badge.textContent = 'UPDATING…';
      badge.style.background = 'rgba(243,156,18,0.15)';
      badge.style.color = 'var(--warning)';
    }
    if (trigBtn) trigBtn.disabled = true;
  } else if (data.update_available) {
    if (badge) {
      badge.textContent = 'UPDATE AVAILABLE';
      badge.style.background = 'rgba(243,156,18,0.15)';
      badge.style.color = 'var(--warning)';
    }
    if (errEl) errEl.textContent = '';
    if (typeInfo) {
      typeInfo.textContent = data.update_type === 'full'
        ? 'Full update — system packages + UART overlays + service restart'
        : 'Simple update — code + pip packages + service restart';
    }
    if (trigBtn) {
      trigBtn.style.display = '';
      trigBtn.textContent = data.update_type === 'full'
        ? 'Install Full Update' : 'Install Update';
      trigBtn.disabled = false;
    }
  } else {
    if (badge) {
      badge.textContent = data.current_version ? 'UP TO DATE' : 'UNKNOWN';
      badge.style.background = 'var(--accent-dim)';
      badge.style.color = 'var(--accent)';
    }
    if (typeInfo) typeInfo.textContent = '';
    if (trigBtn) trigBtn.style.display = 'none';
    if (errEl) errEl.textContent = '';
  }

  const logWrap = document.getElementById('update-progress-wrap');
  if (logWrap) {
    logWrap.style.display =
      (data.update_status === 'running' || (data.log && data.log.length > 0))
        ? '' : 'none';
  }
  _renderUpdateLog(data.log || []);
}

function _renderUpdateLog(lines) {
  const el = document.getElementById('update-log');
  if (!el) return;
  el.textContent = lines.join('\n');
  el.scrollTop = el.scrollHeight;
}

function _startUpdateLogPolling() {
  if (_updatePollTimer) return;
  _updatePollTimer = setInterval(async () => {
    try {
      const data = await api('/update/status');
      _renderUpdateStatus(data);
      if (data.update_status !== 'running') {
        _stopUpdateLogPolling();
        // Service restarted successfully — reload after brief delay
        setTimeout(() => location.reload(), 5000);
      }
    } catch (_) {
      // Server went away — update triggered a restart; wait then reload
      _stopUpdateLogPolling();
      setTimeout(() => location.reload(), 7000);
    }
  }, 1500);
}

function _stopUpdateLogPolling() {
  if (_updatePollTimer) {
    clearInterval(_updatePollTimer);
    _updatePollTimer = null;
  }
}

async function checkForUpdates() {
  const btn = document.getElementById('update-check-btn');
  const err = document.getElementById('update-error-msg');
  if (btn) { btn.disabled = true; btn.textContent = 'Checking…'; }
  try {
    await api('/update/check', { method: 'POST' });
    const fullStatus = await api('/update/status');
    _renderUpdateStatus(fullStatus);
  } catch (_) {
    if (err) err.textContent = 'Network error — could not reach server';
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Check Now'; }
  }
}

async function triggerUpdate() {
  let updateType = 'simple';
  try {
    const status = await api('/update/status');
    updateType = status.update_type || 'simple';
  } catch (_) {}

  const label = updateType === 'full' ? 'Full Update' : 'Update';
  const extra = updateType === 'full'
    ? '• Run full system setup (apt packages, UART overlays)\n' : '';

  if (!confirm(
    `Start ${label}?\n\n` +
    `This will:\n` +
    `• Pull latest code from GitHub\n` +
    `• Install updated Python packages\n` +
    extra +
    `• Restart midi-box service\n\n` +
    `The UI will be unavailable for ~30–60 seconds.`
  )) return;

  const btn = document.getElementById('update-trigger-btn');
  const err = document.getElementById('update-error-msg');
  if (btn) { btn.disabled = true; btn.textContent = 'Starting…'; }
  if (err) err.textContent = '';

  try {
    const result = await api('/update/trigger', {
      method: 'POST',
      body: { type: updateType },
    });
    if (!result.ok) {
      if (err) err.textContent = result.error || 'Failed to start update';
      if (btn) { btn.disabled = false; }
      return;
    }
    const logWrap = document.getElementById('update-progress-wrap');
    if (logWrap) logWrap.style.display = '';
    _startUpdateLogPolling();
  } catch (_) {
    if (err) err.textContent = 'Failed to trigger update';
    if (btn) { btn.disabled = false; btn.textContent = 'Install Update'; }
  }
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

window.addEventListener('resize', () => {
  if (currentPage === 'routing') drawConnections();
});
