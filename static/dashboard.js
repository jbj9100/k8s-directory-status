let currentData = [];
let currentSort = 'du_desc';
let rootDiskInfo = null;

async function loadMounts() {
  try {
    const r = await fetch('/api/mounts');
    const data = await r.json();

    if (!r.ok) throw new Error('Failed to load mounts');

    // / 경로 분리
    rootDiskInfo = data.find(m => m.mountpoint === '/');
    currentData = data.filter(m => m.mountpoint !== '/');

    renderTable();
    updateRootSummary();

    // 비동기로 각 마운트의 DU 크기 조회
    loadAllMountDuSizes();
  } catch (e) {
    console.error('Failed to load mounts:', e);
    document.getElementById('mounts-table').innerHTML = '<div class="loading">Error loading mounts</div>';
  }
}

function updateRootSummary() {
  if (!rootDiskInfo) return;

  const summaryBox = document.getElementById('summary-box');
  summaryBox.style.display = 'flex';
  summaryBox.className = 'summary-box';
  summaryBox.innerHTML = `
    <div class="summary-item">
      <div class="summary-label">Root (/)</div>
      <div class="summary-value" style="font-size:18px;">${rootDiskInfo.used_h} / ${rootDiskInfo.total_h}</div>
      <div style="font-size:11px;opacity:0.8;margin-top:4px;">${rootDiskInfo.free_h} free (${rootDiskInfo.percent}%)</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">Loading...</div>
      <div class="summary-value">-</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">Total DU Size</div>
      <div class="summary-value">-</div>
    </div>
  `;
}

function renderTable() {
  const html = `
    <table>
      <thead>
        <tr>
          <th onclick="sortTable('mountpoint')">Mountpoint</th>
          <th>Device</th>
          <th>Type</th>
          <th>Size</th>
          <th>Avail</th>
          <th>Use%</th>
          <th onclick="sortTable('du_desc')" style="background:#e8f5e9;">DU Size ⬇</th>
        </tr>
      </thead>
      <tbody>
        ${currentData.map(m => `
          <tr>
            <td class="mono" style="max-width:400px;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(m.mountpoint)}">${escapeHtml(m.mountpoint)}</td>
            <td class="mono">${escapeHtml(m.device)}</td>
            <td class="mono">${escapeHtml(m.fstype)}</td>
            <td>${escapeHtml(m.total_h)}</td>
            <td>${escapeHtml(m.free_h)}</td>
            <td>
              <span class="badge">${m.percent}%</span>
            </td>
            <td class="mono du-size" data-path="${escapeHtml(m.mountpoint)}" data-bytes="0">⏳ Loading...</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  document.getElementById('mounts-table').innerHTML = html;
}

async function loadAllMountDuSizes() {
  const duCells = document.querySelectorAll('.du-size');
  const allCells = Array.from(duCells);

  // 배치 20개씩 (전체 조회)
  const batchSize = 20;
  let loaded = 0;

  for (let i = 0; i < allCells.length; i += batchSize) {
    const batch = allCells.slice(i, i + batchSize);
    const promises = batch.map(cell => {
      const path = cell.getAttribute('data-path');
      return loadSingleDuSize(cell, path);
    });
    await Promise.all(promises);

    loaded += batch.length;
    console.log(`Loaded ${loaded}/${allCells.length} mounts`);
  }

  calculateSummary();
  sortTable(currentSort);
}

async function loadSingleDuSize(cell, path) {
  try {
    const r = await fetch(`/api/du?path=${encodeURIComponent(path)}&depth=0`);
    const j = await r.json();

    if (r.ok && j.total_human) {
      const bytes = j.total_bytes || 0;

      // 0B이면 행 숨기기
      if (bytes === 0) {
        const row = cell.closest('tr');
        if (row) {
          row.style.display = 'none';
        }
        return;
      }

      cell.textContent = j.total_human;
      cell.setAttribute('data-bytes', bytes);
    } else {
      cell.textContent = `❌ ${j.detail || r.status}`;
      cell.setAttribute('data-bytes', '0');
      cell.style.color = '#d32f2f';
      cell.style.fontSize = '10px';
    }
  } catch (e) {
    cell.textContent = `⚠️ ${e.message}`;
    cell.setAttribute('data-bytes', '0');
    cell.style.color = '#d32f2f';
    cell.style.fontSize = '10px';
  }

  calculateSummary();
}

function calculateSummary() {
  const duCells = document.querySelectorAll('.du-size');
  let totalBytes = 0;
  let successCount = 0;
  let hiddenCount = 0;

  const excludeFromTotal = [
    '/host/var/lib/containers',
    '/host/var/lib/kubelet/pods',
    '/host/var/lib/containerd'
  ];

  duCells.forEach(cell => {
    const row = cell.closest('tr');
    if (row && row.style.display === 'none') {
      hiddenCount++;
      return;
    }

    const bytes = parseInt(cell.getAttribute('data-bytes') || '0');
    if (bytes > 0) {
      successCount++;

      const path = cell.getAttribute('data-path');
      if (!excludeFromTotal.includes(path)) {
        totalBytes += bytes;
      }
    }
  });

  const visibleCount = duCells.length - hiddenCount;

  const summaryBox = document.getElementById('summary-box');
  summaryBox.style.display = 'flex';
  summaryBox.className = 'summary-box';

  let rootHtml = '';
  if (rootDiskInfo) {
    rootHtml = `
      <div class="summary-item">
        <div class="summary-label">Root (/)</div>
        <div class="summary-value" style="font-size:18px;">${rootDiskInfo.used_h} / ${rootDiskInfo.total_h}</div>
        <div style="font-size:11px;opacity:0.8;margin-top:4px;">${rootDiskInfo.free_h} free (${rootDiskInfo.percent}%)</div>
      </div>
    `;
  }

  summaryBox.innerHTML = `
    ${rootHtml}
    <div class="summary-item">
      <div class="summary-label">Visible / Hidden</div>
      <div class="summary-value">${visibleCount} / ${hiddenCount}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">Total DU Size</div>
      <div class="summary-value">${humanBytes(totalBytes)}</div>
    </div>
  `;
}

function sortTable(type) {
  currentSort = type;

  const tbody = document.querySelector('tbody');
  if (!tbody) return;

  const rows = Array.from(tbody.querySelectorAll('tr'));

  rows.sort((a, b) => {
    if (type === 'mountpoint') {
      const aPath = a.querySelector('td:first-child').textContent;
      const bPath = b.querySelector('td:first-child').textContent;
      return aPath.localeCompare(bPath);
    } else if (type === 'du_desc') {
      const aBytes = parseInt(a.querySelector('.du-size').getAttribute('data-bytes') || '0');
      const bBytes = parseInt(b.querySelector('.du-size').getAttribute('data-bytes') || '0');
      return bBytes - aBytes;
    } else if (type === 'du_asc') {
      const aBytes = parseInt(a.querySelector('.du-size').getAttribute('data-bytes') || '0');
      const bBytes = parseInt(b.querySelector('.du-size').getAttribute('data-bytes') || '0');
      return aBytes - bBytes;
    }
    return 0;
  });

  rows.forEach(row => tbody.appendChild(row));

  document.querySelectorAll('.sort-btn').forEach(btn => btn.classList.remove('active'));
  if (type === 'mountpoint') {
    document.querySelectorAll('.sort-btn')[0]?.classList.add('active');
  } else if (type === 'du_desc') {
    document.querySelectorAll('.sort-btn')[1]?.classList.add('active');
  } else if (type === 'du_asc') {
    document.querySelectorAll('.sort-btn')[2]?.classList.add('active');
  }
}

function humanBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
