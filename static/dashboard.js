let currentData = [];
let currentSort = 'du_desc';

async function loadMounts() {
  try {
    const r = await fetch('/api/mounts');
    const data = await r.json();

    if (!r.ok) throw new Error('Failed to load mounts');

    currentData = data;
    renderTable();

    // 비동기로 각 마운트의 DU 크기 조회
    loadAllMountDuSizes();
  } catch (e) {
    console.error('Failed to load mounts:', e);
    document.getElementById('mounts-table').innerHTML = '<div class="loading">Error loading mounts</div>';
  }
}

function renderTable() {
  const html = `
    <table>
      <thead>
        <tr>
          <th onclick="sortTable('mountpoint')">Mountpoint</th>
          <th>Pod/Container</th>
          <th>Device</th>
          <th>Type</th>
          <th>Size</th>
          <th>Avail</th>
          <th>Use%</th>
          <th onclick="sortTable('du_desc')" style="background:#e8f5e9;">DU Size ⬇</th>
        </tr>
      </thead>
      <tbody>
        ${currentData.map(m => {
    const podInfo = extractPodInfo(m.mountpoint);
    return `
          <tr>
            <td class="mono" style="max-width:300px;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(m.mountpoint)}">${escapeHtml(m.mountpoint)}</td>
            <td class="mono" style="font-size:10px;color:#1565c0;">${escapeHtml(podInfo)}</td>
            <td class="mono">${escapeHtml(m.device)}</td>
            <td class="mono">${escapeHtml(m.fstype)}</td>
            <td>${escapeHtml(m.total_h)}</td>
            <td>${escapeHtml(m.free_h)}</td>
            <td>
              <span class="badge">${m.percent}%</span>
            </td>
            <td class="mono du-size" data-path="${escapeHtml(m.mountpoint)}" data-bytes="0">⏳ Loading...</td>
          </tr>
          `;
  }).join('')}
      </tbody>
    </table>
  `;

  document.getElementById('mounts-table').innerHTML = html;
}

function extractPodInfo(path) {
  // /host/var/lib/kubelet/pods/[pod-uid]/...
  const podMatch = path.match(/\/pods\/([a-f0-9-]{36})/);
  if (podMatch) {
    return `Pod: ${podMatch[1].substring(0, 8)}...`;
  }

  // /host/var/lib/containers/storage/overlay/[hash]/merged
  const containerMatch = path.match(/\/overlay\/([a-f0-9]{64})/);
  if (containerMatch) {
    return `Ctr: ${containerMatch[1].substring(0, 12)}...`;
  }

  // /host/run/containerd/.../[container-id]/rootfs
  const containerdMatch = path.match(/\/k8s\.io\/([a-f0-9]{64})/);
  if (containerdMatch) {
    return `Ctd: ${containerdMatch[1].substring(0, 12)}...`;
  }

  return '-';
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

  // 모든 로딩 완료 후 합산 계산 및 자동 정렬
  calculateSummary();
  sortTable(currentSort);
}

async function loadSingleDuSize(cell, path) {
  try {
    const r = await fetch(`/api/du?path=${encodeURIComponent(path)}&depth=0`);
    const j = await r.json();

    if (r.ok && j.total_human) {
      cell.textContent = j.total_human;
      cell.setAttribute('data-bytes', j.total_bytes || 0);
    } else {
      // 에러 상세 표시
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
}

function calculateSummary() {
  const duCells = document.querySelectorAll('.du-size');
  let totalBytes = 0;
  let successCount = 0;

  duCells.forEach(cell => {
    const bytes = parseInt(cell.getAttribute('data-bytes') || '0');
    if (bytes > 0) {
      totalBytes += bytes;
      successCount++;
    }
  });

  const summaryBox = document.getElementById('summary-box');
  summaryBox.style.display = 'flex';
  summaryBox.className = 'summary-box';
  summaryBox.innerHTML = `
    <div class="summary-item">
      <div class="summary-label">Total Mounts</div>
      <div class="summary-value">${duCells.length}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">Loaded</div>
      <div class="summary-value">${successCount}</div>
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

  // Re-append sorted rows
  rows.forEach(row => tbody.appendChild(row));

  // Update button states
  document.querySelectorAll('.sort-btn').forEach(btn => btn.classList.remove('active'));
  if (type === 'mountpoint') {
    document.querySelectorAll('.sort-btn')[0].classList.add('active');
  } else if (type === 'du_desc') {
    document.querySelectorAll('.sort-btn')[1].classList.add('active');
  } else if (type === 'du_asc') {
    document.querySelectorAll('.sort-btn')[2].classList.add('active');
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
