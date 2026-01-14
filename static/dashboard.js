let currentData = [];
let currentSort = 'du_desc';
let currentNode = '';

async function loadMounts() {
  try {
    // 노드 정보 가져오기
    const nodeRes = await fetch('/api/node-info');
    const nodeInfo = await nodeRes.json();
    currentNode = nodeInfo.node_name || 'Unknown';

    currentData = [];
    renderTable();

    // SSE로 스트리밍 수신 - overlay + emptyDir 모두 조회
    const eventSource = new EventSource('/api/containers/writable/stream?skip_zero=false');

    eventSource.onmessage = function (event) {
      if (event.data === '[DONE]') {
        eventSource.close();
        calculateSummary();
        sortTable(currentSort);
        console.log('완료. 총 ' + currentData.length + ' 항목');
        return;
      }

      try {
        const item = JSON.parse(event.data);
        currentData.push(item);
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
    <div style="margin-bottom:10px;padding:10px;background:#e3f2fd;border-radius:4px;font-size:14px;">
      <strong>🖥️ Connected to: ${escapeHtml(currentNode)} (Aggregator)</strong>
    </div>
    <div style="margin-bottom:10px;padding:8px;background:#fff3e0;border-radius:4px;font-size:11px;">
      <strong>💡 emptyDir의 Pod UID로 Pod 찾기:</strong>
      <pre style="background:#fff;padding:6px;border-radius:3px;margin-top:4px;overflow-x:auto;font-size:10px;">kubectl get pods -A -o custom-columns=NS:.metadata.namespace,POD:.metadata.name,UID:.metadata.uid --no-headers | grep "&lt;Pod UID&gt;"</pre>
    </div>
    <table>
      <thead>
        <tr>
          <th>Type</th>
          <th>Pod / Container</th>
          <th onclick="sortTable('du_desc')" style="background:#ffebee;cursor:pointer;">Actual Size ⬇ (범인 찾기!)</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        ${currentData.length === 0 ? '<tr><td colspan="4" style="text-align:center;opacity:0.6;">조회 중...</td></tr>' : ''}
        ${renderRowsByNode()}
      </tbody>
    </table>
  `;

  document.getElementById('mounts-table').innerHTML = html;
}

function renderRowsByNode() {
  // 노드 목록 추출 (정렬)
  const nodes = [...new Set(currentData.map(d => d.node_name || 'Unknown'))].sort();

  return nodes.map(nodeName => {
    const nodeItems = currentData.filter(d => d.node_name === nodeName || (!d.node_name && nodeName === 'Unknown'));

    // 노드 헤더
    let rows = `
      <tr style="background:#eeeeee;">
        <td colspan="4" style="padding:8px 10px;border-bottom:2px solid #ddd;">
          <strong>📦 Node: ${escapeHtml(nodeName)}</strong> (${nodeItems.length} items)
        </td>
      </tr>
    `;

    // 아이템 렌더링
    rows += nodeItems.map(m => {
      const actualBytes = m.actual_bytes || 0;
      const actualHuman = m.actual_human || '-';
      const actualStatus = m.actual_status || 'unknown';
      const itemType = m.type || '';

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

      // Type 라벨
      let typeLabel = '';
      let typeStyle = 'font-size:10px;padding:2px 6px;border-radius:3px;';
      if (itemType === 'overlay') {
        typeLabel = 'overlay';
        typeStyle += 'background:#e3f2fd;color:#1976d2;';
      } else if (itemType === 'emptydir') {
        typeLabel = 'emptyDir';
        typeStyle += 'background:#fff3e0;color:#f57c00;';
      }

      // Pod/Container 이름
      let nameDisplay = '';
      if (itemType === 'overlay') {
        // overlay: Pod 이름 + Container 이름 + Container ID
        if (m.pod) {
          nameDisplay = `<div style="font-weight:bold;">${escapeHtml(m.pod)}</div>`;
          if (m.container_name) {
            nameDisplay += `<div style="font-size:10px;opacity:0.7;">${escapeHtml(m.container_name)}</div>`;
          }
        }
        nameDisplay += `<div style="font-size:9px;opacity:0.5;">Container ID: ${escapeHtml(m.container_id || '-')}</div>`;
      } else if (itemType === 'emptydir') {
        // emptyDir: 볼륨 이름 + Pod UID만 표시 (명령어는 상단에 한번만)
        const podUid = m.pod_uid || '-';
        nameDisplay = `<div style="font-weight:bold;">emptyDir: ${escapeHtml(m.volume_name || '-')}</div>`;
        nameDisplay += `<div style="font-size:9px;opacity:0.5;">Pod UID: ${escapeHtml(podUid)}</div>`;
      } else {
        nameDisplay = `<div style="font-size:10px;opacity:0.5;">${escapeHtml(m.container_id || m.pod_uid || '-')}</div>`;
      }

      return `
              <tr>
                <td><span style="${typeStyle}">${typeLabel}</span></td>
                <td>${nameDisplay}</td>
                <td class="mono du-size" data-bytes="${actualBytes}" style="${cellStyle}">${cellContent}</td>
                <td>${statusIcon}</td>
              </tr>
            `;
    }).join('');

    return rows;
  }).join('');
}

function calculateSummary() {
  let totalBytes = 0;
  let nonZeroCount = 0;
  let overlayCount = 0;
  let emptydirCount = 0;

  currentData.forEach(m => {
    if (m.type === 'overlay') overlayCount++;
    if (m.type === 'emptydir') emptydirCount++;

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
      <div class="summary-label">총 항목</div>
      <div class="summary-value">${currentData.length}개</div>
      <div style="font-size:10px;opacity:0.7;">overlay: ${overlayCount} / emptyDir: ${emptydirCount}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">사용량 있음 / 없음</div>
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
