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
            <th>Used (FS)</th>
            <th>Avail</th>
            <th>Use%</th>
            <th>DU Size</th>
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
              <td class="mono du-size" data-path="${escapeHtml(m.mountpoint)}">⏳</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;

    document.getElementById('mounts-table').innerHTML = html;

    // 비동기로 각 마운트의 DU 크기 조회
    loadAllMountDuSizes();
  } catch (e) {
    console.error('Failed to load mounts:', e);
    document.getElementById('mounts-table').innerHTML = '<div class="loading">Error loading mounts</div>';
  }
}

async function loadAllMountDuSizes() {
  const duCells = document.querySelectorAll('.du-size');

  // 배치로 처리 (한 번에 5개씩)
  const batchSize = 5;
  const allCells = Array.from(duCells);

  for (let i = 0; i < allCells.length; i += batchSize) {
    const batch = allCells.slice(i, i + batchSize);
    const promises = batch.map(cell => {
      const path = cell.getAttribute('data-path');
      return loadSingleDuSize(cell, path);
    });
    await Promise.all(promises);
  }
}

async function loadSingleDuSize(cell, path) {
  try {
    const r = await fetch(`/api/du?path=${encodeURIComponent(path)}&depth=0`);
    const j = await r.json();

    if (r.ok && j.total_human) {
      cell.textContent = j.total_human;
      cell.style.color = '#2e7d32';
      cell.style.fontWeight = '600';
    } else {
      cell.textContent = '-';
    }
  } catch (e) {
    cell.textContent = '-';
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
