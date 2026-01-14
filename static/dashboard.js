let currentData = [];
let currentSort = 'du_desc';
let rootDiskInfo = null;

async function loadMounts() {
  try {
    // /api/mounts/actual: df 목록 + 실제 사용량(overlay는 upperdir만) 한 번에
    const r = await fetch('/api/mounts/actual?skip_zero=true');
    const result = await r.json();

    if (!r.ok) throw new Error('Failed to load mounts');

    const data = result.mounts || [];

    // / 경로 분리
    rootDiskInfo = data.find(m => m.mountpoint === '/');
    currentData = data.filter(m => m.mountpoint !== '/');

    renderTableWithActual();
    updateRootSummary();
    calculateSummary();
    sortTable(currentSort);
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

function renderTableWithActual() {
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
          <th onclick="sortTable('du_desc')" style="background:#e8f5e9;">Actual Size ⬇</th>
        </tr>
      </thead>
      <tbody>
        ${currentData.map(m => {
    const actualBytes = m.actual_bytes || 0;
    const actualHuman = m.actual_human || '-';
    const actualStatus = m.actual_status || 'unknown';

    let cellContent = actualHuman;
    let cellStyle = '';

    if (actualStatus === 'error') {
      cellContent = `❌ ${actualHuman}`;
      cellStyle = 'color:#d32f2f;font-size:10px;';
    } else if (actualStatus === 'skip') {
      cellContent = 'N/A';
      cellStyle = 'opacity:0.5;';
    }

    return `
            <tr>
              <td class="mono" style="max-width:400px;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(m.mountpoint)}">${escapeHtml(m.mountpoint)}</td>
              <td class="mono">${escapeHtml(m.device)}</td>
              <td class="mono">${escapeHtml(m.fstype)}</td>
              <td>${escapeHtml(m.total_h || '-')}</td>
              <td>${escapeHtml(m.free_h || '-')}</td>
              <td>
                <span class="badge">${m.percent || 0}%</span>
              </td>
              <td class="mono du-size" data-path="${escapeHtml(m.mountpoint)}" data-bytes="${actualBytes}" style="${cellStyle}">${cellContent}</td>
            </tr>
          `;
  }).join('')}
      </tbody>
    </table>
  `;

  document.getElementById('mounts-table').innerHTML = html;
}

// 개별 du 조회 함수 제거 (이미 /api/mounts/actual에서 전부 받음)

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
