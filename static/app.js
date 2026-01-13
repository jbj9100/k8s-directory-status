let currentEntries = [];

// 좌우 카드 크기 조절 기능
document.addEventListener('DOMContentLoaded', function () {
  const resizer = document.getElementById('resizer');
  const leftCard = document.getElementById('leftCard');
  const rightCard = document.getElementById('rightCard');

  if (resizer && leftCard && rightCard) {
    let isResizing = false;

    resizer.addEventListener('mousedown', function (e) {
      isResizing = true;
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', function (e) {
      if (!isResizing) return;

      const container = leftCard.parentElement;
      const containerRect = container.getBoundingClientRect();
      const leftWidth = e.clientX - containerRect.left;
      const totalWidth = containerRect.width;
      const leftPercent = (leftWidth / totalWidth) * 100;

      if (leftPercent > 20 && leftPercent < 80) {
        leftCard.style.flex = `0 0 ${leftPercent}%`;
        rightCard.style.flex = `0 0 ${100 - leftPercent - 1}%`;
      }
    });

    document.addEventListener('mouseup', function () {
      isResizing = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    });
  }

  // 마운트 포인트별 DU 크기 로드
  loadMountDuSizes();
});


function setPath(p) {
  document.getElementById('path').value = p;
  loadPath();
}
function goUp() {
  const cur = (document.getElementById('path').value || "/").trim();
  if (cur === "/") return;
  const parts = cur.split("/").filter(Boolean);
  parts.pop();
  const up = "/" + parts.join("/");
  setPath(up === "" ? "/" : up);
}
function reload() { loadPath(true); }

async function loadPath(force = false) {
  const pathEl = document.getElementById('path');
  let p = (pathEl.value || "/").trim();
  if (!p.startsWith("/")) p = "/" + p;
  pathEl.value = p;

  document.getElementById('err').textContent = "";
  document.getElementById('curPath').textContent = p;
  document.getElementById('total').textContent = "loading…";
  const list = document.getElementById('list');
  list.innerHTML = "<div class='muted'>loading…</div>";

  try {
    const r = await fetch(`/api/du?path=${encodeURIComponent(p)}&depth=1`, { cache: force ? "reload" : "no-store" });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || `오류 발생 (HTTP ${r.status})`);
    document.getElementById('total').textContent = j.total_human || "-";
    currentEntries = j.entries || [];
    renderList(currentEntries);
  } catch (e) {
    document.getElementById('total').textContent = "-";
    list.innerHTML = "";
    document.getElementById('err').textContent = String(e);
  }
}

function renderList(entries) {
  const list = document.getElementById('list');
  list.innerHTML = "";
  if (entries.length === 0) {
    list.innerHTML = "<div class='muted'>No entries (or permission denied / empty)</div>";
    return;
  }
  for (const e of entries) {
    const row = document.createElement('div');
    row.className = "item";
    row.innerHTML = `<div class="mono click" title="${e.path}">${escapeHtml(e.name)}</div><div class="mono">${escapeHtml(e.human)}</div>`;
    row.querySelector('.click').onclick = () => setPath(e.path);
    list.appendChild(row);
  }
}

function sortEntries(order) {
  if (currentEntries.length === 0) return;
  const sorted = [...currentEntries].sort((a, b) => {
    return order === 'asc' ? a.bytes - b.bytes : b.bytes - a.bytes;
  });
  renderList(sorted);
}

function escapeHtml(s) {
  return String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

// 마운트 포인트별 DU 크기 로드
async function loadMountDuSizes() {
  const duCells = document.querySelectorAll('.du-size');

  for (const cell of duCells) {
    const path = cell.getAttribute('data-path');
    if (!path) continue;

    // 비동기로 각 경로의 du 크기 조회
    loadSingleDuSize(cell, path);
  }
}

async function loadSingleDuSize(cell, path) {
  try {
    const r = await fetch(`/api/du?path=${encodeURIComponent(path)}&depth=0`, { cache: "default" });
    const j = await r.json();

    if (r.ok && j.total_human) {
      cell.textContent = j.total_human;
      cell.setAttribute('data-bytes', j.total_bytes || 0);
    } else {
      cell.textContent = '-';
    }
  } catch (e) {
    cell.textContent = '-';
  }
}
