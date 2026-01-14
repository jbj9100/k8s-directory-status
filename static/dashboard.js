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
            <th>Device</th>
            <th>Type</th>
            <th>Size</th>
            <th>Used</th>
            <th>Avail</th>
            <th>Use%</th>
          </tr>
        </thead>
        <tbody>
          ${data.map(m => `
            <tr>
              <td class="mono">${escapeHtml(m.mountpoint)}</td>
              <td class="mono">${escapeHtml(m.device)}</td>
              <td class="mono">${escapeHtml(m.fstype)}</td>
              <td>${escapeHtml(m.total_h)}</td>
              <td>${escapeHtml(m.used_h)}</td>
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
