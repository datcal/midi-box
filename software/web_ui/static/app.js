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
    case 'player': loadPlayer(); break;
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
        <button class="btn btn-sm" style="margin-left:auto;" onclick="openDeviceModal('${esc(d.name)}')">Configure</button>
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
  const [data, devData, netData] = await Promise.all([
    api('/settings'),
    api('/devices'),
    api('/network'),
  ]);

  document.getElementById('setting-platform').value = data.platform;
  document.getElementById('setting-mode').value = data.mode;
  document.getElementById('setting-preset').value = data.preset || '(none)';

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
  launcherInterval = setInterval(pollLauncher, 200);
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

window.addEventListener('resize', () => {
  if (currentPage === 'routing') drawConnections();
});
