"""Single-page HTML dashboard template.

Embedded as a Python string to avoid file-serving complexity.
Chart.js is loaded from CDN; everything else is inline.
"""

DASHBOARD_HTML: str = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Edge Monitor Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0f1117;
    --card: #1a1d27;
    --border: #2a2d3a;
    --text: #e0e0e0;
    --text-dim: #888;
    --accent: #4fc3f7;
    --green: #66bb6a;
    --yellow: #ffa726;
    --red: #ef5350;
    --critical: #d32f2f;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg); color: var(--text);
    min-height: 100vh;
  }
  header {
    background: var(--card); border-bottom: 1px solid var(--border);
    padding: 12px 24px; display: flex; align-items: center; gap: 16px;
  }
  header h1 { font-size: 18px; font-weight: 600; color: var(--accent); }
  .status-dot {
    width: 10px; height: 10px; border-radius: 50%;
    display: inline-block; margin-right: 4px;
  }
  .status-dot.ok { background: var(--green); }
  .status-dot.warn { background: var(--yellow); }
  .status-dot.error { background: var(--red); }
  .header-meta { margin-left: auto; font-size: 12px; color: var(--text-dim); }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 16px; padding: 16px; max-width: 1600px; margin: 0 auto;
  }
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px;
  }
  .card h2 {
    font-size: 13px; font-weight: 600; color: var(--text-dim);
    text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px;
  }
  .gauge-row { display: flex; gap: 12px; flex-wrap: wrap; }
  .gauge {
    flex: 1; min-width: 120px; text-align: center;
    padding: 12px 8px; background: rgba(255,255,255,0.03);
    border-radius: 6px;
  }
  .gauge-value { font-size: 28px; font-weight: 700; line-height: 1.2; }
  .gauge-label { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
  .gauge-value.green { color: var(--green); }
  .gauge-value.yellow { color: var(--yellow); }
  .gauge-value.red { color: var(--red); }
  .chart-container { position: relative; height: 200px; }
  .alert-list { max-height: 300px; overflow-y: auto; }
  .alert-item {
    display: flex; align-items: center; gap: 8px;
    padding: 8px; border-bottom: 1px solid var(--border);
    font-size: 13px;
  }
  .alert-badge {
    padding: 2px 6px; border-radius: 3px; font-size: 11px;
    font-weight: 600; text-transform: uppercase; white-space: nowrap;
  }
  .badge-critical { background: var(--critical); color: #fff; }
  .badge-error { background: var(--red); color: #fff; }
  .badge-warning { background: var(--yellow); color: #000; }
  .badge-info { background: var(--accent); color: #000; }
  .health-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
  }
  .health-item {
    display: flex; justify-content: space-between;
    padding: 6px 8px; background: rgba(255,255,255,0.03);
    border-radius: 4px; font-size: 13px;
  }
  .health-key { color: var(--text-dim); }
  .no-data { text-align: center; color: var(--text-dim); padding: 24px; font-size: 14px; }
  .refresh-indicator {
    display: inline-block; width: 8px; height: 8px;
    border-radius: 50%; background: var(--green);
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }
  .inference-gauge-row {
    display: flex; gap: 16px; align-items: center;
    padding: 8px 0; flex-wrap: wrap;
  }
  .inference-fps-display {
    font-size: 48px; font-weight: 700; line-height: 1;
    min-width: 140px; text-align: center;
    padding: 12px 16px; background: rgba(255,255,255,0.03);
    border-radius: 8px;
  }
  .inference-fps-label {
    font-size: 12px; color: var(--text-dim);
    margin-top: 4px; text-align: center;
  }
  .inference-charts {
    display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
  }
  .inference-chart-container { position: relative; height: 180px; }
  @media (max-width: 768px) {
    .grid { grid-template-columns: 1fr; padding: 8px; }
    .gauge-value { font-size: 22px; }
    .inference-charts { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>

<header>
  <h1>&#x1F4CA; AI Edge Monitor</h1>
  <span class="status-dot ok" id="conn-dot"></span>
  <span id="conn-label" style="font-size:12px">Connecting...</span>
  <div class="header-meta">
    <span class="refresh-indicator"></span>
    <span id="last-update">--</span>
  </div>
</header>

<div class="grid">
  <!-- Gauges -->
  <div class="card" style="grid-column: 1 / -1">
    <h2>System Overview</h2>
    <div class="gauge-row">
      <div class="gauge">
        <div class="gauge-value green" id="g-cpu">--</div>
        <div class="gauge-label">CPU %</div>
      </div>
      <div class="gauge">
        <div class="gauge-value green" id="g-mem">--</div>
        <div class="gauge-label">Memory MB</div>
      </div>
      <div class="gauge">
        <div class="gauge-value green" id="g-power">--</div>
        <div class="gauge-label">Power W</div>
      </div>
      <div class="gauge">
        <div class="gauge-value green" id="g-temp">--</div>
        <div class="gauge-label">Temp &deg;C</div>
      </div>
      <div class="gauge">
        <div class="gauge-value green" id="g-disk">--</div>
        <div class="gauge-label">Disk %</div>
      </div>
      <div class="gauge">
        <div class="gauge-value" id="g-alerts" style="color:var(--accent)">0</div>
        <div class="gauge-label">Active Alerts</div>
      </div>
    </div>
  </div>

  <!-- Inference Performance -->
  <div class="card" style="grid-column: 1 / -1">
    <h2>Inference Performance</h2>
    <div id="inference-panel">
      <div class="inference-gauge-row">
        <div>
          <div class="inference-fps-display green" id="g-fps">--</div>
          <div class="inference-fps-label">FPS</div>
        </div>
        <div class="gauge-row" style="flex:1">
          <div class="gauge">
            <div class="gauge-value" id="g-inf-lat-p50" style="color:var(--accent)">--</div>
            <div class="gauge-label">P50 ms</div>
          </div>
          <div class="gauge">
            <div class="gauge-value" id="g-inf-lat-p95" style="color:var(--accent)">--</div>
            <div class="gauge-label">P95 ms</div>
          </div>
          <div class="gauge">
            <div class="gauge-value" id="g-inf-lat-p99" style="color:var(--accent)">--</div>
            <div class="gauge-label">P99 ms</div>
          </div>
          <div class="gauge">
            <div class="gauge-value" id="g-inf-frames" style="color:var(--accent)">--</div>
            <div class="gauge-label">Frames</div>
          </div>
          <div class="gauge">
            <div class="gauge-value" id="g-inf-gpu" style="color:var(--accent)">--</div>
            <div class="gauge-label">GPU %</div>
          </div>
          <div class="gauge">
            <div class="gauge-value" id="g-inf-power" style="color:var(--accent)">--</div>
            <div class="gauge-label">Power W</div>
          </div>
        </div>
      </div>
      <div class="inference-charts">
        <div>
          <h3 style="font-size:12px;color:var(--text-dim);margin-bottom:8px">FPS Timeline</h3>
          <div class="inference-chart-container"><canvas id="chart-fps"></canvas></div>
        </div>
        <div>
          <h3 style="font-size:12px;color:var(--text-dim);margin-bottom:8px">Latency Distribution</h3>
          <div class="inference-chart-container"><canvas id="chart-latency"></canvas></div>
        </div>
      </div>
    </div>
    <div class="no-data" id="inference-not-configured" style="display:none">Inference monitor not configured</div>
  </div>

  <!-- CPU Chart -->
  <div class="card">
    <h2>CPU Timeline</h2>
    <div class="chart-container"><canvas id="chart-cpu"></canvas></div>
  </div>

  <!-- Memory Chart -->
  <div class="card">
    <h2>Memory Timeline</h2>
    <div class="chart-container"><canvas id="chart-mem"></canvas></div>
  </div>

  <!-- Power Chart -->
  <div class="card">
    <h2>Power Timeline</h2>
    <div class="chart-container"><canvas id="chart-power"></canvas></div>
  </div>

  <!-- Alerts -->
  <div class="card">
    <h2>Alerts</h2>
    <div class="alert-list" id="alert-list">
      <div class="no-data">No alerts</div>
    </div>
  </div>

  <!-- Health -->
  <div class="card">
    <h2>Guardian Health</h2>
    <div class="health-grid" id="health-grid">
      <div class="no-data" style="grid-column:1/-1">Loading...</div>
    </div>
  </div>

  <!-- Network I/O -->
  <div class="card">
    <h2>Network I/O</h2>
    <div class="gauge-row">
      <div class="gauge">
        <div class="gauge-value" id="g-net-send" style="color:var(--accent)">--</div>
        <div class="gauge-label">Send KB/s</div>
      </div>
      <div class="gauge">
        <div class="gauge-value" id="g-net-recv" style="color:var(--accent)">--</div>
        <div class="gauge-label">Recv KB/s</div>
      </div>
      <div class="gauge">
        <div class="gauge-value" id="g-net-conn" style="color:var(--accent)">--</div>
        <div class="gauge-label">Connections</div>
      </div>
    </div>
  </div>
</div>

<script>
const POLL_INTERVAL = 3000;
const MAX_POINTS = 120;

// --- Chart setup ---
function makeChart(ctx, label, color, yMax) {
  return new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [{
      label, data: [],
      borderColor: color, backgroundColor: color + '22',
      borderWidth: 1.5, fill: true, tension: 0.3, pointRadius: 0,
    }]},
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 200 },
      scales: {
        x: { display: false },
        y: { min: 0, max: yMax, grid: { color: '#2a2d3a' },
             ticks: { color: '#888', font: { size: 10 } } }
      },
      plugins: { legend: { display: false } }
    }
  });
}

const chartCpu = makeChart(
  document.getElementById('chart-cpu').getContext('2d'),
  'CPU %', '#4fc3f7', 100);
const chartMem = makeChart(
  document.getElementById('chart-mem').getContext('2d'),
  'Memory MB', '#66bb6a', null);
const chartPower = makeChart(
  document.getElementById('chart-power').getContext('2d'),
  'Power W', '#ffa726', null);

// --- Inference charts ---
const INFERENCE_TARGET_FPS = 30; // default target; overridden by config if available
let inferenceTargetFps = INFERENCE_TARGET_FPS;

const chartFps = makeChart(
  document.getElementById('chart-fps').getContext('2d'),
  'FPS', '#66bb6a', null);

const latencyChart = new Chart(
  document.getElementById('chart-latency').getContext('2d'), {
    type: 'bar',
    data: {
      labels: ['P50', 'P95', 'P99'],
      datasets: [{
        label: 'Latency ms',
        data: [0, 0, 0],
        backgroundColor: ['#4fc3f7', '#ffa726', '#ef5350'],
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 200 },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#888', font: { size: 11 } } },
        y: { min: 0, grid: { color: '#2a2d3a' },
             ticks: { color: '#888', font: { size: 10 } } }
      },
      plugins: { legend: { display: false } }
    }
  });

function fpsColor(fps) {
  if (fps >= inferenceTargetFps * 0.9) return 'green';
  if (fps >= inferenceTargetFps * 0.7) return 'yellow';
  return 'red';
}

// --- Gauge color helper ---
function gaugeColor(val, warn, crit) {
  if (crit && val >= crit) return 'red';
  if (warn && val >= warn) return 'yellow';
  return 'green';
}

// --- Format helpers ---
function fmtBytes(bps) {
  if (bps == null) return '--';
  const kbs = bps / 1024;
  return kbs >= 1024 ? (kbs / 1024).toFixed(1) + ' MB/s' : kbs.toFixed(1) + ' KB/s';
}
function fmtTime(ts_ms) {
  return new Date(ts_ms).toLocaleTimeString();
}

// --- Push data to chart ---
function pushChart(chart, label, value) {
  chart.data.labels.push(label);
  chart.data.datasets[0].data.push(value);
  if (chart.data.labels.length > MAX_POINTS) {
    chart.data.labels.shift();
    chart.data.datasets[0].data.shift();
  }
  chart.update('none');
}

// --- Render alerts ---
function renderAlerts(data) {
  const el = document.getElementById('alert-list');
  const alerts = data.active_alerts || [];
  document.getElementById('g-alerts').textContent = alerts.length;
  if (alerts.length === 0) {
    el.innerHTML = '<div class="no-data">No active alerts</div>';
    return;
  }
  el.innerHTML = alerts.map(a => {
    const sev = (a.severity || 'info').toLowerCase();
    const badgeClass = 'badge-' + (sev === 'critical' ? 'critical' : sev);
    return `<div class="alert-item">
      <span class="alert-badge ${badgeClass}">${a.severity}</span>
      <span style="flex:1">${a.message || a.rule_name}</span>
      <span style="color:var(--text-dim);font-size:11px">${a.metric}: ${a.current_value}</span>
    </div>`;
  }).join('');
}

// --- Render health ---
function renderHealth(data) {
  const el = document.getElementById('health-grid');
  if (data.error || data.status === 'not_configured') {
    el.innerHTML = '<div class="no-data" style="grid-column:1/-1">Guardian not configured</div>';
    return;
  }
  const items = [
    ['Status', data.status || '--'],
    ['CPU overhead', data.cpu_percent != null ? data.cpu_percent.toFixed(2) + '%' : '--'],
    ['RSS MB', data.rss_mb != null ? data.rss_mb.toFixed(1) : '--'],
    ['Degraded', data.degraded ? 'Yes' : 'No'],
    ['Circuit breaker', data.circuit_breaker_state || '--'],
    ['Uptime', data.uptime_sec != null ? Math.round(data.uptime_sec) + 's' : '--'],
  ];
  el.innerHTML = items.map(([k, v]) =>
    `<div class="health-item"><span class="health-key">${k}</span><span>${v}</span></div>`
  ).join('');
}

// --- Render inference ---
function renderInference(data) {
  const panel = document.getElementById('inference-panel');
  const notConfigured = document.getElementById('inference-not-configured');
  if (data.error || data.status === 'not_configured') {
    panel.style.display = 'none';
    notConfigured.style.display = 'block';
    return;
  }
  panel.style.display = 'block';
  notConfigured.style.display = 'none';

  const fps = data.fps;
  const p50 = data.latency_p50_ms;
  const p95 = data.latency_p95_ms;
  const p99 = data.latency_p99_ms;

  // FPS large display
  const gFps = document.getElementById('g-fps');
  gFps.textContent = fps != null ? fps.toFixed(1) : '--';
  gFps.className = 'inference-fps-display ' + (fps != null ? fpsColor(fps) : '');

  // Latency gauges
  const gP50 = document.getElementById('g-inf-lat-p50');
  gP50.textContent = p50 != null ? p50.toFixed(1) : '--';
  const gP95 = document.getElementById('g-inf-lat-p95');
  gP95.textContent = p95 != null ? p95.toFixed(1) : '--';
  const gP99 = document.getElementById('g-inf-lat-p99');
  gP99.textContent = p99 != null ? p99.toFixed(1) : '--';

  // Other gauges
  const gFrames = document.getElementById('g-inf-frames');
  gFrames.textContent = data.frame_count != null ? data.frame_count : '--';
  const gGpu = document.getElementById('g-inf-gpu');
  gGpu.textContent = data.gpu_util_during_inference != null
    ? data.gpu_util_during_inference.toFixed(1) : '--';
  const gPow = document.getElementById('g-inf-power');
  gPow.textContent = data.power_during_inference != null
    ? data.power_during_inference.toFixed(1) : '--';

  // FPS timeline chart
  if (fps != null) {
    pushChart(chartFps, fmtTime(Date.now()), fps);
  }

  // Latency distribution bar chart
  if (p50 != null || p95 != null || p99 != null) {
    latencyChart.data.datasets[0].data = [p50 || 0, p95 || 0, p99 || 0];
    latencyChart.update('none');
  }
}

// --- Polling loop ---
let connected = false;

async function poll() {
  try {
    const [sumRes, alertRes, healthRes, sysRes, infRes] = await Promise.all([
      fetch('/api/summary').then(r => r.json()),
      fetch('/api/alerts').then(r => r.json()),
      fetch('/api/health').then(r => r.json()),
      fetch('/api/system').then(r => r.json()).catch(() => ({})),
      fetch('/api/inference').then(r => r.json()).catch(() => ({})),
    ]);

    // Connection status
    if (!connected) {
      connected = true;
      document.getElementById('conn-dot').className = 'status-dot ok';
      document.getElementById('conn-label').textContent = 'Connected';
    }

    // Update gauges from summary
    const cpu = sumRes.cpu_avg;
    const mem = sumRes.mem_used_avg_mb;
    const power = sumRes.power_avg_watt;
    const temp = sumRes.temp_max_c;
    const disk = sysRes.disk_usage_percent;

    const gCpu = document.getElementById('g-cpu');
    gCpu.textContent = cpu != null ? cpu.toFixed(1) : '--';
    gCpu.className = 'gauge-value ' + gaugeColor(cpu, 70, 90);

    const gMem = document.getElementById('g-mem');
    gMem.textContent = mem != null ? mem.toFixed(0) : '--';
    gMem.className = 'gauge-value ' + gaugeColor(
      sumRes.mem_total_mb ? (mem / sumRes.mem_total_mb * 100) : 0, 70, 85);

    const gPow = document.getElementById('g-power');
    gPow.textContent = power != null ? power.toFixed(1) : '--';
    gPow.className = 'gauge-value green';

    const gTmp = document.getElementById('g-temp');
    gTmp.textContent = temp != null ? temp.toFixed(1) : '--';
    gTmp.className = 'gauge-value ' + gaugeColor(temp, 60, 80);

    const gDsk = document.getElementById('g-disk');
    gDsk.textContent = disk != null ? disk.toFixed(1) : '--';
    gDsk.className = 'gauge-value ' + gaugeColor(disk, 80, 90);

    // Push chart data
    const now = fmtTime(Date.now());
    if (cpu != null) pushChart(chartCpu, now, cpu);
    if (mem != null) pushChart(chartMem, now, mem);
    if (power != null) pushChart(chartPower, now, power);

    // Network
    if (sysRes.net_send_rate_bps != null) {
      document.getElementById('g-net-send').textContent =
        (sysRes.net_send_rate_bps / 1024).toFixed(1);
    }
    if (sysRes.net_recv_rate_bps != null) {
      document.getElementById('g-net-recv').textContent =
        (sysRes.net_recv_rate_bps / 1024).toFixed(1);
    }
    if (sysRes.net_connections != null) {
      document.getElementById('g-net-conn').textContent = sysRes.net_connections;
    }

    // Alerts & health
    renderAlerts(alertRes);
    renderHealth(healthRes);
    renderInference(infRes);

    // Timestamp
    document.getElementById('last-update').textContent =
      'Updated ' + new Date().toLocaleTimeString();

  } catch (err) {
    connected = false;
    document.getElementById('conn-dot').className = 'status-dot error';
    document.getElementById('conn-label').textContent = 'Disconnected';
    console.error('Poll error:', err);
  }
}

// Start polling
poll();
setInterval(poll, POLL_INTERVAL);
</script>
</body>
</html>
"""
