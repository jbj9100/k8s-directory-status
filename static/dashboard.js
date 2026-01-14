async function loadAll() {
  // 실시간 갱신: CPU, 메모리, I/O만
  await Promise.all([
    loadSystemStats(),
    loadMounts()
  ]);
}

async function loadPathsSummaryManual() {
  // 수동 로드만 가능 (느린 작업)
  await loadPathsSummary();
}

async function loadSystemStats() {
  try {
    const r = await fetch('/api/system/stats');
    const data = await r.json();

    if (!r.ok) throw new Error('Failed to load system stats');

    const html = `
      <div class="metric" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
        <div class="metric-label">CPU Usage</div>
        <div class="metric-value">${data.cpu.percent.toFixed(1)}%</div>
        <div class="metric-sub">${data.cpu.count} cores</div>
      </div>
      <div class="metric" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);">
        <div class="metric-label">Memory</div>
        <div class="metric-value">${data.memory.percent.toFixed(1)}%</div>
        <div class="metric-sub">${data.memory.used_h} / ${data.memory.total_h}</div>
      </div>
      <div class="metric" style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);">
        <div class="metric-label">Disk I/O</div>
        <div class="metric-value">💾</div>
        <div class="metric-sub">R: ${data.disk_io.read_h} | W: ${data.disk_io.write_h}</div>
      </div>
      <div class="metric" style="background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);">
        <div class="metric-label">Network I/O</div>
        <div class="metric-value">🌐</div>
        <div class="metric-sub">↓ ${data.net_io.recv_h} | ↑ ${data.net_io.sent_h}</div>
      </div>
    `;

    document.getElementById('system-metrics').innerHTML = html;

    // Top 프로세스 렌더링
    if (data.top_processes && data.top_processes.length > 0) {
      const processHtml = `
        <table>
          <thead>
            <tr>
              <th>PID</th>
              <th>Name</th>
              <th>CPU %</th>
              <th>MEM %</th>
            </tr>
          </thead>
          <tbody>
            ${data.top_processes.map(p => `
              <tr>
                <td class="mono">${p.pid}</td>
                <td>${escapeHtml(p.name)}</td>
                <td>${p.cpu.toFixed(1)}%</td>
                <td>${p.mem.toFixed(1)}%</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
      document.getElementById('top-processes').innerHTML = processHtml;
    }
  } catch (e) {
    console.error('Failed to load system stats:', e);
    document.getElementById('system-metrics').innerHTML = '<div class="loading">Error loading system stats</div>';
  }
}

async function loadPathsSummary() {
  try {
    const r = await fetch('/api/paths/summary');
    const data = await r.json();

    if (!r.ok) throw new Error('Failed to load paths');

    const html = data.paths.map(p => {
      const shortPath = p.path.replace('/host', '');
      const status = p.status === 'ok' ? '' : ' (Error)';
      return `
        <div class="path-item">
          <div class="path-name">${escapeHtml(shortPath)}</div>
          <div class="path-size">${escapeHtml(p.total_human)}${status}</div>
        </div>
      `;
    }).join('');

    document.getElementById('paths-grid').innerHTML = html;
  } catch (e) {
    console.error('Failed to load paths:', e);
    document.getElementById('paths-grid').innerHTML = '<div class="loading">Error loading paths</div>';
  }
}

async function loadMounts() {
  try {
    const r = await fetch('/api/mounts');
    const data = await r.json();

    if (!r.ok) throw new Error('Failed to load mounts');

    const html = `
      <table>
        <thead>
          <tr>
            <th>Mountpoint</th>
            <th>Type</th>
            <th>Used / Total</th>
            <th>Free</th>
            <th>Usage</th>
          </tr>
        </thead>
        <tbody>
          ${data.map(m => `
            <tr>
              <td class="mono">${escapeHtml(m.mountpoint)}</td>
              <td class="mono">${escapeHtml(m.fstype)}</td>
              <td>${escapeHtml(m.used_h)} / ${escapeHtml(m.total_h)}</td>
              <td>${escapeHtml(m.free_h)}</td>
              <td>
                <span class="badge">${m.percent}%</span>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;

    document.getElementById('mounts-table').innerHTML = html;
  } catch (e) {
    console.error('Failed to load mounts:', e);
    document.getElementById('mounts-table').innerHTML = '<div class="loading">Error loading mounts</div>';
  }
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
