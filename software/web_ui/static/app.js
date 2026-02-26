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
let _currentBpm = 120;  // tracks last known BPM across all inputs

// Sync all BPM inputs/displays to the same value without triggering re-POST
function _syncBpmInputs(bpm) {
  _currentBpm = bpm;
  document.querySelectorAll('[data-bpm-sync]').forEach(el => {
    if (el.matches(':focus')) return;
    if (el.tagName === 'INPUT') el.value = Math.round(bpm);
    else el.textContent = Math.round(bpm);
  });
}

// Sync all clock source selects; update Design B badge and Design C chips
function _syncClockSourceSelects(source) {
  const isExt = source !== 'internal';
  document.querySelectorAll('[data-clock-src-sync]').forEach(el => {
    if (el.value !== source) el.value = source;
  });
  // Design B badge
  const badge = document.getElementById('clock-b-badge');
  if (badge) {
    badge.textContent = isExt ? 'EXT' : 'INT';
    badge.className = 'clock-mod-badge' + (isExt ? ' clock-mod-badge-ext' : '');
  }
  // Design C chips
  const intChip = document.getElementById('clock-c-int-chip');
  if (intChip) intChip.classList.toggle('active', !isExt);
  const extChip = document.getElementById('clock-c-ext-chip');
  if (extChip) {
    extChip.classList.toggle('active', isExt);
    if (isExt && extChip.value !== source) extChip.value = source;
  }
}

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
  history.replaceState(null, '', '#' + page);
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
    case 'player': loadPlayer(); break;
    case 'settings': loadSettings(); break;
    case 'logs': startLogs(); break;
    case 'system': startSystem(); break;
    case 'virtualhere': loadVirtualhere(); break;
  }
}

// --- API helpers ---

async function api(path, opts = {}, timeoutMs = 6000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(`/api${path}`, {
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    return await resp.json();
  } catch (e) {
    return {};
  } finally {
    clearTimeout(timer);
  }
}

// --- Dashboard ---

async function loadDashboard() {
  const [devData, routeData, monData, clockData] = await Promise.all([
    api('/devices'),
    api('/routes'),
    api('/monitor?limit=1'),
    api('/clock'),
  ]);

  devices = devData.devices;
  window._deviceDisplayNames = devData.device_display_names || {};
  window._unconfiguredDevices = devData.unconfigured_devices || [];
  window._rawPorts = devData.raw_ports || [];
  routes = routeData.routes;
  document.getElementById('mode-badge').textContent = devData.mode;

  // Populate Design B & C clock selects with connected devices
  if (clockData) {
    const current = clockData.source || 'internal';
    const deviceOptions = devices.map(d => {
      const sel = d.name === current ? ' selected' : '';
      return `<option value="${esc(d.name)}"${sel}>${esc(d.name)}</option>`;
    }).join('');
    const bSrc = document.getElementById('clock-b-source');
    if (bSrc) {
      bSrc.innerHTML = `<option value="internal"${current === 'internal' ? ' selected' : ''}>Internal</option>` + deviceOptions;
    }
    const cExt = document.getElementById('clock-c-ext-chip');
    if (cExt) {
      cExt.innerHTML = `<option value="">EXT &#9662;</option>` + deviceOptions;
      if (current !== 'internal') cExt.value = current;
    }
    _syncClockSourceSelects(current);
    _syncBpmInputs(clockData.bpm || 120);
    _setLauncherBpmDisabled(current !== 'internal');
  }

  // Stats
  document.getElementById('stat-devices').textContent = devices.length;
  document.getElementById('stat-routes').textContent = routes.length;
  document.getElementById('stat-messages').textContent = monData.stats.total || 0;
  document.getElementById('device-count').textContent = devices.length;

  // New-device banner
  const unconfigured = window._unconfiguredDevices || [];
  const banner = document.getElementById('new-devices-banner');
  if (banner) {
    if (unconfigured.length > 0) {
      document.getElementById('new-devices-text').textContent =
        `${unconfigured.length} new device${unconfigured.length > 1 ? 's' : ''} detected — setup needed`;
      banner.style.display = 'flex';
    } else {
      banner.style.display = 'none';
    }
  }

  // Device list
  const list = document.getElementById('device-list');
  if (devices.length === 0) {
    list.innerHTML = '<div style="padding:20px; color:var(--text-muted); text-align:center;">No MIDI devices detected. Connect a device and click Rescan.</div>';
    return;
  }

  const displayNames = window._deviceDisplayNames || {};
  list.innerHTML = devices.map(d => {
    const label = displayNames[d.name] || d.name;
    const needsSetup = unconfigured.includes(d.name);
    const setupBadge = needsSetup
      ? `<span style="font-size:10px; background:#c97d10; color:#fff; border-radius:3px; padding:1px 5px; margin-left:6px;">Setup needed</span>`
      : '';
    return `
    <div class="device-card">
      <div class="device-name">${esc(label)}${setupBadge}</div>
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
    </div>`;
  }).join('');
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

// Live BPM update while dragging slider — visual only, no network request
function setBpmLive(val) {
  _syncBpmInputs(Math.max(20, Math.min(300, parseFloat(val) || 120)));
}

// Unified clock source setter — used by dashboard (B & C) and launcher page
async function setClockSourceAll(source) {
  if (!source) return;  // ignore empty EXT placeholder
  await api('/clock/source', { method: 'POST', body: { source } });
  _syncClockSourceSelects(source);
  _setLauncherBpmDisabled(source !== 'internal');
  if (source === 'internal') {
    ['clock-lost-banner', 'clock-b-lost', 'clock-c-lost'].forEach(id => {
      const el = document.getElementById(id); if (el) el.style.display = 'none';
    });
  }
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
  const [data, clockData, devData] = await Promise.all([
    api('/launcher'),
    api('/clock'),
    api('/devices'),
  ]);
  launcherData = data;

  // Populate clock source select with Internal + all devices
  const srcSel = document.getElementById('launcher-clock-source');
  if (srcSel) {
    const current = (clockData && clockData.source) || 'internal';
    srcSel.innerHTML = '<option value="internal">Internal</option>';
    (devData.devices || []).forEach(d => {
      const sel = d.name === current ? ' selected' : '';
      srcSel.innerHTML += `<option value="${esc(d.name)}"${sel}>${esc(d.name)}</option>`;
    });
    srcSel.value = current;
  }

  // Update clock controls
  updateClockControls(data.clock || {}, clockData || {});

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
  if (poll.bpm) _syncBpmInputs(poll.bpm);
}

function updateClockControls(launcherClock, globalClock) {
  const bpm = Math.round((globalClock && globalClock.bpm) || launcherClock.bpm || 120);
  const source = (globalClock && globalClock.source) || 'internal';
  const isExternal = source !== 'internal';

  _syncBpmInputs(bpm);

  const qSel = document.getElementById('launcher-quantum');
  if (qSel) qSel.value = launcherClock.quantum || 'bar';

  const tsSel = document.getElementById('launcher-timesig');
  if (tsSel) tsSel.value = launcherClock.beats_per_bar || 4;

  const srcSel = document.getElementById('launcher-clock-source');
  if (srcSel && srcSel.value !== source) srcSel.value = source;

  _setLauncherBpmDisabled(isExternal);

  const lostBanner = document.getElementById('clock-lost-banner');
  if (lostBanner) lostBanner.style.display = (globalClock && globalClock.ext_clock_lost) ? '' : 'none';
}

function _setLauncherBpmDisabled(disabled) {
  document.querySelectorAll('[data-bpm-sync], [data-bpm-step]').forEach(el => {
    el.disabled = disabled;
  });
  // Visual dim on BPM wrapper elements
  document.querySelectorAll('.clock-bpm, .clock-mod-bpm-row, .clock-bpm-display-row, .clock-c-steps').forEach(el => {
    el.style.opacity = disabled ? '0.45' : '';
  });
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

// Clock controls — all delegate to setClockSourceAll
async function setLauncherClockSource(source) {
  return setClockSourceAll(source);
}

async function adjustBpm(delta) {
  const bpm = Math.max(20, Math.min(300, _currentBpm + delta));
  _syncBpmInputs(bpm);
  await api('/clock/bpm', { method: 'POST', body: { bpm } });
}

async function setBpm(val) {
  const bpm = Math.max(20, Math.min(300, parseFloat(val) || 120));
  _syncBpmInputs(bpm);
  await api('/clock/bpm', { method: 'POST', body: { bpm } });
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
  // Fire both simultaneously — panic gives instant note-off, stop halts the layer
  await Promise.all([
    api(`/launcher/layers/${layerId}/stop`, { method: 'POST' }),
    api('/panic', { method: 'POST' }),
  ]);
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
    `<option value="${esc(d.name)}" data-channel="${d.midi_channel || 0}">${esc(d.name)}${d.midi_channel ? ' (ch ' + d.midi_channel + ')' : ''}</option>`
  ).join('');

  // Auto-fill channel from device config when destination changes
  destSelect.onchange = function() {
    const selected = this.options[this.selectedIndex];
    document.getElementById('layer-add-ch').value = selected ? (parseInt(selected.dataset.channel) || 0) : 0;
  };

  document.getElementById('layer-add-name').value = '';
  destSelect.dispatchEvent(new Event('change'));  // pre-fill for initial selection
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
let playerCurrentFolder = null;   // null = root, string = subfolder name
let playerDestination = null;
let playerCurrentStatus = {};
let _playerBpm = 120;  // player-local BPM (120 = tempo_factor 1.0)

async function playerAdjustBpm(delta) {
  const bpm = Math.max(20, Math.min(300, _playerBpm + delta));
  _playerBpm = bpm;
  const el = document.getElementById('player-bpm');
  if (el && !el.matches(':focus')) el.value = bpm;
  await api('/player/tempo', { method: 'POST', body: { tempo: bpm / 120.0 } });
}

async function playerSetBpm(val) {
  const bpm = Math.max(20, Math.min(300, parseFloat(val) || 120));
  _playerBpm = bpm;
  await api('/player/tempo', { method: 'POST', body: { tempo: bpm / 120.0 } });
}

async function loadPlayer() {
  const [playerData, devData] = await Promise.all([
    api('/player'),
    api('/devices'),
  ]);

  // Populate destination select (output devices only)
  const destSelect = document.getElementById('player-dest');
  const outputDevices = (devData.devices || []).filter(d =>
    d.direction === 'both' || d.direction === 'out'
  );
  destSelect.innerHTML = outputDevices.map(d =>
    `<option value="${esc(d.name)}">${esc(d.name)}</option>`
  ).join('');

  // Restore saved destination
  if (playerDestination) {
    destSelect.value = playerDestination;
  }
  if (!destSelect.value && outputDevices.length) {
    playerDestination = outputDevices[0].name;
    destSelect.value = playerDestination;
  }

  // Restore status
  const status = playerData.status || {};
  playerCurrentStatus = status;
  updatePlayerStatusBadge(status);

  // Restore loop checkbox
  document.getElementById('player-loop').checked = status.loop || false;

  // Init upload zone (idempotent)
  initUploadZone();

  // Navigate to root and render
  playerCurrentFolder = null;
  await refreshMidiFileList();

  // Start polling
  if (playerInterval) clearInterval(playerInterval);
  playerInterval = setInterval(pollPlayerStatus, 600);
}

// -------------------------------------------------------------------
// Upload zone
// -------------------------------------------------------------------

function initUploadZone() {
  const zone = document.getElementById('player-upload-zone');
  if (!zone || zone._uploadInited) return;
  zone._uploadInited = true;

  zone.addEventListener('click', (e) => {
    if (e.target.closest('button') || e.target.tagName === 'INPUT') return;
    document.getElementById('midi-upload').click();
  });

  zone.addEventListener('dragenter', (e) => {
    e.preventDefault();
    zone.classList.add('drag-over');
  });

  zone.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });

  zone.addEventListener('dragleave', (e) => {
    if (!zone.contains(e.relatedTarget)) zone.classList.remove('drag-over');
  });

  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const files = Array.from(e.dataTransfer.files).filter(f =>
      /\.(mid|midi)$/i.test(f.name)
    );
    if (files.length === 0) {
      showUploadError('Only .mid / .midi files are supported.');
      return;
    }
    uploadMidiFiles(files, playerCurrentFolder);
  });
}

async function uploadMidiFiles(files, folder) {
  const zone = document.getElementById('player-upload-zone');
  const progressBar = document.getElementById('upload-progress-bar');
  const progressWrap = document.getElementById('upload-progress');
  const errorEl = document.getElementById('upload-error');

  errorEl.style.display = 'none';
  zone.classList.add('uploading');
  progressWrap.style.display = 'block';
  progressBar.style.width = '0%';

  const fileArray = Array.from(files);
  const errors = [];

  for (let i = 0; i < fileArray.length; i++) {
    const f = fileArray[i];
    progressBar.style.width = Math.round((i / fileArray.length) * 100) + '%';

    const formData = new FormData();
    formData.append('file', f);
    if (folder) formData.append('folder', folder);

    try {
      const resp = await fetch('/api/player/upload', { method: 'POST', body: formData });
      const data = await resp.json();
      if (!data.ok) errors.push(`${f.name}: ${data.error || 'upload failed'}`);
    } catch {
      errors.push(`${f.name}: network error`);
    }
  }

  progressBar.style.width = '100%';
  await new Promise(r => setTimeout(r, 300));

  zone.classList.remove('uploading');
  progressWrap.style.display = 'none';
  progressBar.style.width = '0%';

  // Reset input so the same file can be re-uploaded
  const inp = document.getElementById('midi-upload');
  if (inp) inp.value = '';

  if (errors.length > 0) showUploadError(errors.join(' | '));

  await refreshMidiFileList();
}

function showUploadError(msg) {
  const el = document.getElementById('upload-error');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 6000);
}

// -------------------------------------------------------------------
// File browser
// -------------------------------------------------------------------

async function refreshMidiFileList() {
  const params = playerCurrentFolder
    ? '?folder=' + encodeURIComponent(playerCurrentFolder)
    : '';
  const data = await api('/player/files' + params);
  renderMidiFileList(data, playerCurrentFolder, playerCurrentStatus);
}

function renderMidiFileList(data, currentFolder, status) {
  const browser = document.getElementById('midi-file-browser');
  const breadcrumb = document.getElementById('player-breadcrumb');

  // Breadcrumb
  if (currentFolder) {
    breadcrumb.innerHTML =
      `<span class="player-breadcrumb-item" onclick="navigateToFolder(null)">Root</span>` +
      `<span class="player-breadcrumb-sep">&#8250;</span>` +
      `<span class="player-breadcrumb-current">${esc(currentFolder)}</span>`;
  } else {
    breadcrumb.innerHTML = `<span class="player-breadcrumb-current">Root</span>`;
  }

  const folders = data.folders || [];
  const files = data.files || [];
  const playingFile = status.file || null;
  const playingFolder = status.folder !== undefined ? status.folder : null;

  if (folders.length === 0 && files.length === 0) {
    browser.innerHTML = `
      <div style="padding:24px; text-align:center; color:var(--text-muted); font-size:13px;">
        ${currentFolder
          ? 'This folder is empty.'
          : 'No MIDI files yet. Drop files onto the zone above.'}
      </div>`;
    return;
  }

  let html = '<ul class="midi-file-list">';

  // Folders (only at root level)
  for (const folder of folders) {
    const fn = esc(folder.name);
    html += `
      <li class="midi-folder-item" onclick="navigateToFolder('${fn}')">
        <span class="midi-folder-icon">&#128193;</span>
        <span class="midi-folder-name">${fn}</span>
        <span class="midi-folder-meta">${folder.file_count} file${folder.file_count !== 1 ? 's' : ''}</span>
        <div class="btn-group" onclick="event.stopPropagation()">
          <button class="btn btn-sm" onclick="renameFolder('${fn}')">Rename</button>
          <button class="btn btn-sm btn-danger" onclick="deleteFolder('${fn}')">Delete</button>
        </div>
      </li>`;
  }

  // Files
  for (const f of files) {
    const isPlaying = f.name === playingFile
      && f.folder === playingFolder
      && (status.playing || status.paused);
    const playIcon = isPlaying ? '&#9632;' : '&#9654;';
    const itemClass = isPlaying ? 'midi-file-item playing' : 'midi-file-item';
    const fn = esc(f.name);
    const folderArg = currentFolder ? `'${esc(currentFolder)}'` : 'null';

    html += `
      <li class="${itemClass}">
        <button class="midi-file-play-btn"
                onclick="playerPlayFile('${fn}', ${folderArg})"
                title="${isPlaying ? 'Stop' : 'Play'}">${playIcon}</button>
        <div class="midi-file-info">
          <div class="midi-file-name">${fn}</div>
          <div class="midi-file-meta">${f.duration}s &middot; ${f.tracks} track${f.tracks !== 1 ? 's' : ''}</div>
        </div>
        <div class="midi-file-actions">
          <button class="btn btn-sm" onclick="moveFile('${fn}', ${folderArg})">Move</button>
          <button class="btn btn-sm" onclick="renameMidiFile('${fn}', ${folderArg})">Rename</button>
          <button class="btn btn-sm btn-danger" onclick="deleteMidiFile('${fn}', ${folderArg})">Delete</button>
        </div>
      </li>`;
  }

  html += '</ul>';
  browser.innerHTML = html;
}

// -------------------------------------------------------------------
// Playback controls
// -------------------------------------------------------------------

async function playerPlayFile(name, folder) {
  const status = playerCurrentStatus;
  // Toggle: if this file is already active, stop it
  if (status.file === name && status.folder === folder && (status.playing || status.paused)) {
    await playerStop();
    return;
  }
  const dest = document.getElementById('player-dest').value;
  if (!dest) return;
  const loop = document.getElementById('player-loop').checked;

  await api('/player/play', {
    method: 'POST',
    body: { file: name, folder, destination: dest, loop, tempo: _playerBpm / 120.0 },
  });

  // Optimistic update
  playerCurrentStatus = { ...status, playing: true, paused: false, file: name, folder };
  updatePlayerStatusBadge(playerCurrentStatus);
  await refreshMidiFileList();
}

async function playerStop() {
  await api('/player/stop', { method: 'POST' });
  playerCurrentStatus = {};
  updatePlayerStatusBadge({});
  await refreshMidiFileList();
}

async function pollPlayerStatus() {
  if (currentPage !== 'player') {
    clearInterval(playerInterval);
    playerInterval = null;
    return;
  }
  const data = await api('/player');
  if (!data || !data.status) return;

  const status = data.status;
  const prevFile = playerCurrentStatus.file;
  const prevFolder = playerCurrentStatus.folder;
  const prevPlaying = playerCurrentStatus.playing || playerCurrentStatus.paused;
  playerCurrentStatus = status;

  // Sync player-local BPM display from status
  if (status.bpm) {
    _playerBpm = status.bpm;
    const bpmEl = document.getElementById('player-bpm');
    if (bpmEl && !bpmEl.matches(':focus')) bpmEl.value = Math.round(status.bpm);
  }

  updatePlayerStatusBadge(status);

  // Refresh file list only when playing state or active file changes
  const fileChanged = status.file !== prevFile || status.folder !== prevFolder;
  const stateChanged = (status.playing || status.paused) !== prevPlaying;
  if (fileChanged || stateChanged) {
    await refreshMidiFileList();
  }
}

function updatePlayerStatusBadge(status) {
  const badge = document.getElementById('player-status-badge');
  const stopBtn = document.getElementById('player-stop-btn');
  if (!badge) return;

  if (status.playing) {
    badge.textContent = 'PLAYING';
    badge.className = 'rec-state-badge playing';
    if (stopBtn) stopBtn.disabled = false;
  } else if (status.paused) {
    badge.textContent = 'PAUSED';
    badge.className = 'rec-state-badge stopped';
    if (stopBtn) stopBtn.disabled = false;
  } else {
    badge.textContent = 'STOPPED';
    badge.className = 'rec-state-badge';
    if (stopBtn) stopBtn.disabled = true;
  }
}

function playerSetLoop(checked) {
  api('/player/loop', { method: 'POST', body: { loop: checked } });
}

function playerDestinationChanged() {
  playerDestination = document.getElementById('player-dest').value;
}

// -------------------------------------------------------------------
// Folder navigation & management
// -------------------------------------------------------------------

async function navigateToFolder(name) {
  playerCurrentFolder = name;
  await refreshMidiFileList();
}

async function createFolder() {
  const name = prompt('New folder name:');
  if (!name || !name.trim()) return;
  const result = await api('/player/mkdir', { method: 'POST', body: { name: name.trim() } });
  if (!result.ok) {
    alert('Could not create folder: ' + (result.error || 'unknown error'));
    return;
  }
  await navigateToFolder(result.name || name.trim());
}

async function renameFolder(name) {
  const newName = prompt(`Rename folder "${name}" to:`, name);
  if (!newName || !newName.trim() || newName.trim() === name) return;
  const result = await api('/player/rename_folder', {
    method: 'POST',
    body: { old_name: name, new_name: newName.trim() },
  });
  if (!result.ok) {
    alert('Rename failed: ' + (result.error || 'unknown error'));
    return;
  }
  await refreshMidiFileList();
}

async function deleteFolder(name) {
  if (!confirm(`Delete folder "${name}" and ALL its MIDI files? This cannot be undone.`)) return;
  const result = await api('/player/delete_folder', { method: 'POST', body: { name } });
  if (!result.ok) {
    alert('Delete failed: ' + (result.error || 'unknown error'));
    return;
  }
  await refreshMidiFileList();
}

// -------------------------------------------------------------------
// File management
// -------------------------------------------------------------------

async function renameMidiFile(name, folder) {
  const suggestion = name.replace(/\.mid$/i, '');
  const newName = prompt(`Rename "${name}" to:`, suggestion);
  if (!newName || !newName.trim()) return;
  const result = await api('/player/rename', {
    method: 'POST',
    body: { old_name: name, new_name: newName.trim(), folder },
  });
  if (!result.ok) {
    alert('Rename failed: ' + (result.error || 'unknown error'));
    return;
  }
  await refreshMidiFileList();
}

async function deleteMidiFile(name, folder) {
  if (!confirm(`Delete "${name}"?`)) return;
  await api('/player/delete', { method: 'POST', body: { file: name, folder } });
  await refreshMidiFileList();
}

async function moveFile(name, srcFolder) {
  const data = await api('/player/files');
  const folders = (data.folders || []).map(f => f.name);
  const options = ['(Root)', ...folders.filter(f => f !== srcFolder)];

  if (options.length === 1 && srcFolder === null) {
    alert('No folders exist yet. Create a folder first with "+ Folder".');
    return;
  }

  const choiceStr = prompt(
    `Move "${name}" to:\n` +
    options.map((o, i) => `  ${i}: ${o}`).join('\n') +
    '\n\nEnter number:'
  );
  if (choiceStr === null || choiceStr === '') return;

  const idx = parseInt(choiceStr, 10);
  if (isNaN(idx) || idx < 0 || idx >= options.length) return;

  const dstFolder = idx === 0 ? null : options[idx];
  if (dstFolder === srcFolder) return;

  const result = await api('/player/move', {
    method: 'POST',
    body: { filename: name, src_folder: srcFolder, dst_folder: dstFolder },
  });
  if (!result.ok) {
    alert('Move failed: ' + (result.error || 'unknown error'));
    return;
  }

  playerCurrentFolder = dstFolder;
  await refreshMidiFileList();
}

// --- Device Config Modal ---

let pendingDeviceName = null;

function openDeviceModal(name) {
  pendingDeviceName = name;
  const dev = devices.find(d => d.name === name);
  if (!dev) return;

  const displayNames = window._deviceDisplayNames || {};
  document.getElementById('device-modal-name').textContent = displayNames[name] || name;
  document.getElementById('device-internal-name').textContent = name;
  document.getElementById('device-display-name').value = displayNames[name] || '';
  document.getElementById('device-direction').value = dev.direction || 'both';
  document.getElementById('device-type').value = dev.device_type || 'unknown';
  document.getElementById('device-channel').value = dev.midi_channel || 0;

  // Port selector — only for USB devices
  const portRow = document.getElementById('device-port-row');
  const portSel = document.getElementById('device-port-select');
  if (dev.port_type === 'usb') {
    portRow.style.display = '';
    const ports = window._rawPorts || [];
    portSel.innerHTML = ports.map(p =>
      `<option value="${esc(p)}"${p === dev.port_id ? ' selected' : ''}>${esc(p)}</option>`
    ).join('');
    // If current port_id is not in the list (stale), add it as a note
    if (dev.port_id && !ports.includes(dev.port_id)) {
      portSel.insertAdjacentHTML('afterbegin',
        `<option value="${esc(dev.port_id)}" selected>${esc(dev.port_id)} (current, not found)</option>`);
    }
  } else {
    portRow.style.display = 'none';
  }

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
  const display_name = document.getElementById('device-display-name').value.trim();
  const dev = devices.find(d => d.name === pendingDeviceName);
  const port_id = (dev?.port_type === 'usb')
    ? document.getElementById('device-port-select').value
    : '';

  await api(`/devices/${encodeURIComponent(pendingDeviceName)}/config`, {
    method: 'POST',
    body: { direction, device_type, midi_channel, display_name, port_id },
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
let vhInterval = null;

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
  // Read-only BPM display (from unified ClockManager)
  const bpmDisplay = document.getElementById('rec-bpm-display');
  if (bpmDisplay) bpmDisplay.textContent = `${Math.round(data.bpm || 120)} BPM`;

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
    while (dots.length < bpb) {
      dotsEl.appendChild(Object.assign(document.createElement('span'), {className:'beat-dot'}));
    }
    const allDots = dotsEl.querySelectorAll('.beat-dot');
    allDots.forEach((d, i) => {
      d.style.display = i < bpb ? '' : 'none';
      d.classList.toggle('active', i === (data.beat || 0) && data.transport_running);
    });
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

async function recSetQuantize(q) { await api('/recorder/clock', { method: 'POST', body: { quantize: q } }); }

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

// --- Info Popover ---

const INFO_DATA = {
  'launcher-clock-mode': {
    title: 'Clock Source',
    musician: 'Internal: MIDI Box generates its own clock. Set the BPM here and everything runs at that tempo.\n\nExternal device: MIDI Box syncs to incoming MIDI clock from your hardware (drum machine, DAW). BPM auto-detected from the device.\n\nIf the external device stops sending clock, MIDI Box falls back to internal automatically and shows a warning.',
    dev: 'Internal = ClockManager internal ticker at 60.0 / (bpm × 96) s per tick.\nExternal = on_midi_clock_tick() called per 0xF8 from selected device; EMA BPM detection; watchdog falls back after 2 s of silence.',
  },
  'launcher-bpm': {
    title: 'BPM — Beats Per Minute',
    musician: 'Sets the playback speed of the internal clock. All clips launch and loop in sync with this tempo.\n\nRange: 20–300 BPM. Grayed out when EXT clock mode is active (tempo is controlled by external hardware).',
    dev: 'Sets bpm on ClipLauncher. Tick interval = 60.0 / (bpm × 96) s at 96 PPQ internal resolution. MIDI clock (0xF8) emitted every 4 internal ticks = 24 PPQ standard.',
  },
  'launcher-quantum': {
    title: 'Launch Quantum',
    musician: 'Decides when a clip starts or stops playing. "Bar" means clips always launch at the beginning of the next bar, keeping everything in time. "Beat" is more immediate — clips launch on the next beat.',
    dev: 'Quantization boundary in internal ticks:\nBeat = 96 ticks\nBar = 96 × beats_per_bar\n2bar = 96 × bpb × 2\n4bar = 96 × bpb × 4\nClip launch queued, fires at next boundary.',
  },
  'rec-quantize': {
    title: 'Quantize / Loop Length Snap',
    musician: 'Controls how the recording length is rounded when you stop.\n\n"Free" — records exactly as long as you play. No snapping.\n\n"Bar" — the loop length rounds up to the next complete bar. Even if you stop mid-bar, the loop plays the full bar. This ensures seamless rhythmic looping.\n\nCount-in: When Quantize is not Free, beat dots pulse before recording starts — waiting for the next quantum boundary.',
    dev: 'On stop: quantized_len = ((elapsed_ticks // qt) + 1) × qt.\nCount-in waits for next quantum boundary (timeout 30s).\n96 PPQ internal resolution.\nQt values: free=0, 1/16=24, 1/8=48, 1/4=96, bar=96×bpb, 2bar×2, 4bar×4.',
  },
  'rec-auto-play': {
    title: 'Auto-Play After Recording',
    musician: 'When ON, your recording automatically starts playing back the moment you stop recording — no need to press Play manually. Useful for quick looping workflows.',
    dev: 'Sets QuickRecorder.auto_play flag. On state transition recording → stopped, if auto_play is True, _play() is called immediately.',
  },
  'rec-record-btn': {
    title: 'RECORD Button',
    musician: 'Press to start capturing all live MIDI from hardware inputs.\n\nPress again (or the foot pedal) to stop recording.\n\nIf Quantize is not "Free", you\'ll see a count-in: the beat dots pulse while the recorder waits for the right beat to start. Recording begins automatically on the next quantum boundary.',
    dev: 'Calls /api/recorder/toggle → quick_recorder.toggle().\nState machine: idle → count_in (if quantize≠free) → recording → stopped.\nCaptures ALL hardware MIDI inputs. MIDI player and looper excluded.\nFoot pedal triggers the same toggle().',
  },
};

function showInfoPopover(btn, key) {
  const data = INFO_DATA[key];
  if (!data) return;

  const popover = document.getElementById('info-popover');
  const content = document.getElementById('info-popover-content');
  if (!popover || !content) return;

  content.innerHTML = `
    <div class="info-popover-title">${esc(data.title)}</div>
    <div class="info-popover-musician">${esc(data.musician).replace(/\n/g, '<br>')}</div>
    ${data.dev ? `
    <div class="info-popover-dev-section">
      <div class="info-popover-dev-label">&#128187; Developer</div>
      <div class="info-popover-dev">${esc(data.dev).replace(/\n/g, '<br>')}</div>
    </div>` : ''}
  `;

  // Position near button, keep within viewport
  const rect = btn.getBoundingClientRect();
  const popW = 340;
  let left = rect.right + 10;
  let top  = rect.top;

  if (left + popW > window.innerWidth - 8) {
    left = rect.left - popW - 10;
  }
  if (left < 8) left = 8;
  if (top + 300 > window.innerHeight - 8) {
    top = window.innerHeight - 310;
  }
  if (top < 8) top = 8;

  popover.style.left = left + 'px';
  popover.style.top  = top  + 'px';
  // Remove any stale listener BEFORE the current click event bubbles to document.
  // This prevents the old listener from closing the popover we just opened.
  document.removeEventListener('click', _closeInfoOnOutside);

  popover.classList.add('active');

  // Register a persistent close-on-outside listener after this event finishes.
  setTimeout(() => {
    document.addEventListener('click', _closeInfoOnOutside);
  }, 10);
}

function _closeInfoOnOutside(e) {
  const popover = document.getElementById('info-popover');
  if (!popover) return;
  // Only close (and remove listener) when the click is outside the popover.
  // Clicks inside the popover (reading, scrolling) are ignored so the listener stays.
  if (!popover.contains(e.target)) {
    popover.classList.remove('active');
    document.removeEventListener('click', _closeInfoOnOutside);
  }
}

function closeInfoPopover() {
  document.getElementById('info-popover')?.classList.remove('active');
  document.removeEventListener('click', _closeInfoOnOutside);
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
    try {
      const data = await api('/poll');
      updateSidebarLive(data);
      if (currentPage === 'dashboard') updateDashboardActivity(data);
    } catch (_) { /* ignore transient failures */ }
  }, 2000);
}

function updateSidebarLive(data) {
  // Mode badge (STANDALONE / DAW / etc.)
  const badge = document.getElementById('mode-badge');
  if (badge && data.mode) badge.textContent = data.mode;

  const isExt = data.clock_source && data.clock_source !== 'internal';
  const effectiveBpm = (isExt && data.ext_bpm) ? data.ext_bpm : (data.bpm || 120);

  // Clock mode label (INT / EXT)
  const clockMode = document.getElementById('sidebar-clock-mode');
  if (clockMode) clockMode.textContent = isExt ? 'EXT' : 'INT';

  // Sidebar BPM display
  const bpmEl = document.getElementById('sidebar-bpm');
  if (bpmEl) bpmEl.innerHTML = `${Math.round(effectiveBpm)} <small>BPM</small>`;

  // Keep all BPM inputs and clock source dropdowns in sync
  _syncBpmInputs(effectiveBpm);
  if (data.clock_source !== undefined) _syncClockSourceSelects(data.clock_source);
  _setLauncherBpmDisabled(isExt);

  // External clock lost banners (sidebar + dashboard B + dashboard C)
  const lost = data.ext_clock_lost;
  ['clock-lost-banner', 'clock-b-lost', 'clock-c-lost'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = lost ? '' : 'none';
  });
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

// --- VirtualHere USB Share ---

async function loadVirtualhere() {
  const [vhData, netData] = await Promise.all([
    api('/virtualhere'),
    api('/network'),
  ]);
  _renderVirtualhere(vhData, netData);

  if (vhInterval) clearInterval(vhInterval);
  vhInterval = setInterval(async () => {
    if (currentPage !== 'virtualhere') {
      clearInterval(vhInterval); vhInterval = null; return;
    }
    const [d, n] = await Promise.all([api('/virtualhere'), api('/network')]);
    _renderVirtualhere(d, n);
  }, 5000);
}

function _renderVirtualhere(vhData, netData) {
  const running   = vhData.running   || false;
  const installed = vhData.installed || false;

  const banner = document.getElementById('vh-warning-banner');
  if (banner) banner.style.display = running ? '' : 'none';

  const badge = document.getElementById('vh-status-badge');
  if (badge) {
    badge.textContent = running ? 'RUNNING' : 'STOPPED';
    badge.style.background = running ? 'rgba(46,204,113,0.15)' : 'rgba(231,76,60,0.15)';
    badge.style.color = running ? 'var(--success)' : 'var(--danger)';
  }

  // Show INSTALLED badge and disable install button once binary is present
  const installedBadge = document.getElementById('vh-installed-badge');
  if (installedBadge) installedBadge.style.display = installed ? '' : 'none';
  const setupBtn = document.getElementById('vh-setup-btn');
  if (setupBtn && installed) {
    setupBtn.textContent = '\u2699 Re-install VirtualHere';
  }

  const startBtn = document.getElementById('vh-start-btn');
  const stopBtn  = document.getElementById('vh-stop-btn');
  if (startBtn) startBtn.disabled = running || !installed;
  if (stopBtn)  stopBtn.disabled  = !running;

  const addrEl = document.getElementById('vh-server-addr');
  if (addrEl && netData && netData.ip) addrEl.textContent = `${netData.ip}:7575`;

  const logEl = document.getElementById('vh-log');
  if (logEl) {
    const lines = vhData.log || [];
    if (lines.length === 0) {
      logEl.innerHTML = running
        ? '<span style="color:var(--text-muted);">No log output yet…</span>'
        : '<span style="color:var(--text-muted);">Start the server to see logs…</span>';
    } else {
      logEl.textContent = lines.join('\n');
      logEl.scrollTop = logEl.scrollHeight;
    }
  }
}

async function vhStart() {
  const msg = document.getElementById('vh-action-msg');
  const btn = document.getElementById('vh-start-btn');
  if (btn) btn.disabled = true;
  if (msg) { msg.textContent = 'Starting…'; msg.style.color = 'var(--warning)'; }
  const result = await api('/virtualhere/start', { method: 'POST' });
  if (msg) {
    msg.textContent = result.ok ? 'Started.' : (result.error || 'Failed — check sudoers setup');
    msg.style.color = result.ok ? 'var(--success)' : 'var(--danger)';
  }
  const [d, n] = await Promise.all([api('/virtualhere'), api('/network')]);
  _renderVirtualhere(d, n);
  setTimeout(() => { if (msg) msg.textContent = ''; }, 4000);
}

async function vhStop() {
  const msg = document.getElementById('vh-action-msg');
  const btn = document.getElementById('vh-stop-btn');
  if (btn) btn.disabled = true;
  if (msg) { msg.textContent = 'Stopping…'; msg.style.color = 'var(--warning)'; }
  const result = await api('/virtualhere/stop', { method: 'POST' });
  if (msg) {
    msg.textContent = result.ok ? 'Stopped.' : (result.error || 'Failed — check sudoers setup');
    msg.style.color = result.ok ? 'var(--success)' : 'var(--danger)';
  }
  const [d, n] = await Promise.all([api('/virtualhere'), api('/network')]);
  _renderVirtualhere(d, n);
  setTimeout(() => { if (msg) msg.textContent = ''; }, 4000);
}

async function vhSetup() {
  const btn = document.getElementById('vh-setup-btn');
  const msg = document.getElementById('vh-setup-msg');
  const out = document.getElementById('vh-setup-output');

  if (btn) { btn.disabled = true; btn.textContent = 'Installing…'; }
  if (msg) { msg.textContent = 'Downloading and installing (may take ~30 s)…'; msg.style.color = 'var(--warning)'; }
  if (out) { out.style.display = ''; out.textContent = ''; }

  const result = await api('/virtualhere/setup', { method: 'POST' }, 130000);

  if (out) {
    out.textContent = result.output || (result.error || 'No output.');
    out.scrollTop = out.scrollHeight;
  }
  if (msg) {
    msg.textContent = result.ok ? 'Installed successfully.' : 'Installation failed — see output above.';
    msg.style.color = result.ok ? 'var(--success)' : 'var(--danger)';
  }
  if (btn) { btn.disabled = false; btn.textContent = '\u2699 Install VirtualHere'; }

  // Refresh status to reflect newly installed service
  const [d, n] = await Promise.all([api('/virtualhere'), api('/network')]);
  _renderVirtualhere(d, n);
}

// --- Hash-based navigation ---

function handleHash() {
  const hash = window.location.hash.replace('#', '') || 'dashboard';
  navigateTo(hash);
}

window.addEventListener('hashchange', handleHash);

// --- Init ---

document.addEventListener('DOMContentLoaded', async () => {
  // Load settings first so performance mode is applied before any page renders
  const settings = await api('/settings');
  _updatePerfBtn(!!settings.performance_mode);
  handleHash();
  startPolling();
});

window.addEventListener('resize', () => {
  if (currentPage === 'routing') drawConnections();
});
