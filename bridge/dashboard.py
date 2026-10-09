"""Usage dashboard HTML + data helpers for the Free TTS Studio bridge.

A single-page HTML view served at `/dashboard` that polls
`/api/dashboard-data` every 5 seconds and renders:
  - engine + bridge health
  - counts (total jobs, in flight, completed, failed)
  - recent jobs table
  - recent output files with download links

Auto-refresh uses simple fetch + setInterval; no JS framework.
"""

import time

# Server start time (filled in by bridge.py at import).
_BRIDGE_START_TS = time.time()


def bridge_uptime_seconds():
    return max(0, int(time.time() - _BRIDGE_START_TS))


def render_dashboard_html():
    """Return the full HTML for /dashboard (no auth, served like the engine UI)."""
    return DASHBOARD_HTML


def build_dashboard_data(job_store, engine_health_fn, engine_get_fn):
    """Compose the JSON payload for /api/dashboard-data.

    `engine_get_fn` is bridge.engine_get(path) -- we call it against
    `/api/files` so we don't have to know the engine's internal layout.
    """
    import json
    up, _ = engine_health_fn()
    jobs = job_store.list_recent(50)
    counts = {'total': len(jobs), 'queued': 0, 'running': 0, 'done': 0, 'failed': 0}
    total_duration_s = 0.0
    for j in jobs:
        s = j.get('status', '')
        if s in counts:
            counts[s] += 1
        if isinstance(j.get('duration'), (int, float)):
            total_duration_s += j['duration']

    # Pull file list from the engine. If the engine is down, fall back to empty.
    file_rows = []
    try:
        _, body = engine_get_fn('/api/files')
        files = json.loads(body).get('files', [])
        for f in files[:20]:
            file_rows.append({'name': f, 'url': f'/v1/files/{f}'})
    except Exception:
        pass

    return {
        'ok': True,
        'engine': 'up' if up else 'down',
        'bridge_uptime_s': bridge_uptime_seconds(),
        'counts': counts,
        'total_audio_s': round(total_duration_s, 2),
        'jobs': jobs[:20],
        'files': file_rows,
        'fetched_at': time.time(),
    }


# --- HTML -----------------------------------------------------------------
DASHBOARD_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TTS Bridge Dashboard</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    background: #0f1115; color: #e6e8ee;
  }
  header {
    padding: 16px 24px; border-bottom: 1px solid #23262e; background: #15181f;
    display: flex; align-items: baseline; gap: 16px;
  }
  header h1 { margin: 0; font-size: 18px; }
  header small { color: #8b93a3; }
  main { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
  .card {
    background: #15181f; border: 1px solid #23262e; border-radius: 10px;
    padding: 14px;
  }
  .card .label { color: #8b93a3; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
  .card .value { font-size: 22px; font-weight: 600; margin-top: 4px; font-variant-numeric: tabular-nums; }
  .dot {
    display: inline-block; width: 10px; height: 10px; border-radius: 50%;
    vertical-align: middle; margin-right: 6px;
  }
  .dot.up { background: #4ade80; box-shadow: 0 0 6px #4ade80; }
  .dot.down { background: #f87171; box-shadow: 0 0 6px #f87171; }
  .panel {
    background: #15181f; border: 1px solid #23262e; border-radius: 10px;
    padding: 14px; margin-top: 16px;
  }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 6px; text-align: left; border-bottom: 1px solid #1d2129; }
  th { color: #8b93a3; font-weight: 500; }
  td.mono { font-family: ui-monospace, Consolas, monospace; color: #aab2c0; }
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 999px;
    font-size: 11px; font-weight: 600; text-transform: uppercase;
  }
  .badge.queued  { background: #2a2f3a; color: #aab2c0; }
  .badge.running { background: #1e40af; color: #bfdbfe; }
  .badge.done    { background: #14532d; color: #bbf7d0; }
  .badge.failed  { background: #7f1d1d; color: #fecaca; }
  .footer { color: #8b93a3; font-size: 12px; margin-top: 24px; text-align: center; }
  a { color: #7aa2f7; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>
<header>
  <h1>Free TTS Bridge Dashboard</h1>
  <small id="fetched">loading...</small>
</header>
<main>
  <div class="grid">
    <div class="card">
      <div class="label">Engine</div>
      <div class="value"><span class="dot" id="dot-engine"></span><span id="engine">?</span></div>
    </div>
    <div class="card">
      <div class="label">Bridge uptime</div>
      <div class="value" id="uptime">--</div>
    </div>
    <div class="card">
      <div class="label">Total jobs</div>
      <div class="value" id="total">0</div>
    </div>
    <div class="card">
      <div class="label">In flight</div>
      <div class="value" id="inflight">0</div>
    </div>
    <div class="card">
      <div class="label">Done</div>
      <div class="value" id="done">0</div>
    </div>
    <div class="card">
      <div class="label">Failed</div>
      <div class="value" id="failed">0</div>
    </div>
    <div class="card">
      <div class="label">Total audio</div>
      <div class="value" id="audios">0.0s</div>
    </div>
  </div>

  <div class="panel">
    <h2 style="margin:0 0 10px;font-size:14px;color:#c9cfda">Recent jobs</h2>
    <table id="jobs">
      <thead><tr>
        <th>Job</th><th>Status</th><th>Voice</th><th>Duration</th><th>Created</th><th>File</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="panel">
    <h2 style="margin:0 0 10px;font-size:14px;color:#c9cfda">Recent output files</h2>
    <table id="files">
      <thead><tr><th>File</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="footer">
    Auto-refresh every 5 seconds. Auth: <span class="mono">Authorization: Bearer &lt;key&gt;</span>
  </div>
</main>
<script>
const $ = (id) => document.getElementById(id);

function fmtTime(ts) {
  if (!ts) return '-';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}
function fmtUptime(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return h + 'h ' + m + 'm';
  if (m) return m + 'm ' + sec + 's';
  return sec + 's';
}

async function refresh() {
  try {
    const r = await fetch('/api/dashboard-data');
    const d = await r.json();
    $('engine').textContent = d.engine;
    $('dot-engine').className = 'dot ' + (d.engine === 'up' ? 'up' : 'down');
    $('uptime').textContent = fmtUptime(d.bridge_uptime_s);
    $('total').textContent = d.counts.total;
    $('inflight').textContent = d.counts.queued + d.counts.running;
    $('done').textContent = d.counts.done;
    $('failed').textContent = d.counts.failed;
    $('audios').textContent = d.total_audio_s.toFixed(2) + 's';

    const tbody = document.querySelector('#jobs tbody');
    tbody.innerHTML = '';
    d.jobs.forEach((j) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="mono">${j.job_id ? j.job_id.substring(0,8) : '?'}</td>
        <td><span class="badge ${j.status}">${j.status}</span></td>
        <td>${j.voice || '-'}</td>
        <td>${typeof j.duration === 'number' ? j.duration.toFixed(2) + 's' : '-'}</td>
        <td class="mono">${fmtTime(j.created_at)}</td>
        <td>${j.file ? '<a href="' + j.file + '" target="_blank">' + j.file.split('/').pop() + '</a>' : '-'}</td>
      `;
      tbody.appendChild(tr);
    });
    if (!d.jobs.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:#8b93a3;text-align:center">No jobs yet.</td></tr>';
    }

    const ftbody = document.querySelector('#files tbody');
    ftbody.innerHTML = '';
    d.files.forEach((f) => {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td><a href="' + f.url + '" target="_blank">' + f.name + '</a></td>';
      ftbody.appendChild(tr);
    });
    if (!d.files.length) {
      ftbody.innerHTML = '<tr><td style="color:#8b93a3;text-align:center">No files yet.</td></tr>';
    }

    $('fetched').textContent = 'updated ' + fmtTime(d.fetched_at);
  } catch (e) {
    $('fetched').textContent = 'fetch error: ' + e.message;
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>'''
