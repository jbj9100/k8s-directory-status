let currentData = [];
let currentSort = 'du_desc';

async function loadMounts() {
  try {
    currentData = [];
    renderTable();

    // SSE로 스트리밍 수신 - Pod writable layer만 조회 (0인 것도 포함)
    const eventSource = new EventSource('/api/containers/writable/stream?skip_zero=false');

    eventSource.onmessage = function (event) {
      if (event.data === '[DONE]') {
        eventSource.close();
        calculateSummary();
        sortTable(currentSort);
        console.log('완료. 총 ' + currentData.length + ' 컨테이너');
        return;
      }

      try {
        const container = JSON.parse(event.data);
        currentData.push({
          mountpoint: container.mountpoint,
          container_id: container.container_id,
          upperdir: container.upperdir,
          actual_bytes: container.actual_bytes,
          actual_human: container.actual_human,
          actual_status: container.actual_status,
        });
        renderTable();
      } catch (e) {
        console.error('파싱 오류:', e);
      }
    };

    eventSource.onerror = function (err) {
      console.error('SSE 오류:', err);
      eventSource.close();
      document.getElementById('mounts-table').innerHTML = '<div class="loading">오류 발생</div>';
    };

  } catch (e) {
    console.error('로드 실패:', e);
    document.getElementById('mounts-table').innerHTML = '<div class="loading">오류 발생</div>';
  }
}

function renderTable() {
  const html = `
    <table>
      <thead>
        <tr>
          <th>Container ID</th>
          <th onclick="sortTable('mountpoint')" style="cursor:pointer;">Mountpoint (rootfs)</th>
          <th onclick="sortTable('du_desc')" style="background:#ffebee;cursor:pointer;">Actual Size ⬇ (범인 찾기!)</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        ${currentData.length === 0 ? '<tr><td colspan="4" style="text-align:center;opacity:0.6;">조회 중...</td></tr>' : ''}
        ${currentData.map(m => {
    const actualBytes = m.actual_bytes || 0;
    const actualHuman = m.actual_human || '-';
    const actualStatus = m.actual_status || 'unknown';

    let cellContent = actualHuman;
    let cellStyle = 'font-weight:bold;';
    let statusIcon = '✅';

    if (actualStatus === 'error') {
      cellContent = actualHuman;
      cellStyle = 'color:#d32f2f;font-size:11px;';
      statusIcon = '❌';
    } else if (actualBytes > 1024 * 1024 * 1024) {
      cellStyle = 'color:#d32f2f;font-weight:bold;font-size:14px;';
      statusIcon = '🔥';
    } else if (actualBytes > 100 * 1024 * 1024) {
      cellStyle = 'color:#f57c00;font-weight:bold;';
      statusIcon = '⚠️';
    }

    return `
            <tr>
              <td class="mono" style="font-size:11px;">${escapeHtml(m.container_id || '-')}</td>
              <td class="mono" style="max-width:400px;overflow:hidden;text-overflow:ellipsis;font-size:10px;" title="${escapeHtml(m.mountpoint)}">${escapeHtml(m.mountpoint)}</td>
              <td class="mono du-size" data-bytes="${actualBytes}" style="${cellStyle}">${cellContent}</td>
              <td>${statusIcon}</td>
            </tr>
          `;
  }).join('')}
      </tbody>
    </table>
  `;

  document.getElementById('mounts-table').innerHTML = html;
}

function calculateSummary() {
  let totalBytes = 0;
  let nonZeroCount = 0;

  currentData.forEach(m => {
    if (m.actual_status === 'ok' && m.actual_bytes > 0) {
      totalBytes += m.actual_bytes;
      nonZeroCount++;
    }
  });

  const zeroCount = currentData.length - nonZeroCount;

  const summaryBox = document.getElementById('summary-box');
  summaryBox.style.display = 'flex';
  summaryBox.innerHTML = `
    <div class="summary-item">
      <div class="summary-label">총 컨테이너</div>
      <div class="summary-value">${currentData.length}개</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">writable 있음 / 없음</div>
      <div class="summary-value" style="color:#d32f2f;">${nonZeroCount}개</div>
      <div style="font-size:11px;opacity:0.7;">/ ${zeroCount}개</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">총 writable 사용량</div>
      <div class="summary-value">${humanBytes(totalBytes)}</div>
    </div>
  `;
}

function sortTable(type) {
  currentSort = type;

  if (type === 'du_desc') {
    currentData.sort((a, b) => (b.actual_bytes || 0) - (a.actual_bytes || 0));
  } else if (type === 'mountpoint') {
    currentData.sort((a, b) => (a.mountpoint || '').localeCompare(b.mountpoint || ''));
  }

  renderTable();
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
