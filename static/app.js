// ---------------------------------------------------------------------------
// Chigua Video Downloader — frontend
// ---------------------------------------------------------------------------

let pollingTimer = null;

// ---------------------------------------------------------------------------
// Submit tasks
// ---------------------------------------------------------------------------
async function submitTasks() {
  const urls = document.getElementById("urls").value.trim();
  if (!urls) return alert("请输入至少一个文章地址");

  const downloadDir = document.getElementById("downloadDir").value.trim() || "/downloads";
  const btn = document.getElementById("submitBtn");
  btn.disabled = true;
  btn.textContent = "⏳ 提交中...";

  try {
    const resp = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls, download_dir: downloadDir }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      alert("提交失败: " + (err.detail || resp.statusText));
      return;
    }
    document.getElementById("urls").value = "";
    startPolling();
  } catch (e) {
    alert("网络错误: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "⬇️ 开始下载";
  }
}

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------
function startPolling() {
  if (pollingTimer) return;
  refresh();
  pollingTimer = setInterval(refresh, 500);
}

function stopPolling() {
  if (pollingTimer) { clearInterval(pollingTimer); pollingTimer = null; }
}

// ---------------------------------------------------------------------------
// Refresh UI
// ---------------------------------------------------------------------------
async function refresh() {
  try {
    const resp = await fetch("/api/tasks");
    const tasks = await resp.json();
    renderTasks(tasks);
  } catch {}
}

function renderTasks(tasks) {
  const container = document.getElementById("taskList");
  const countEl = document.getElementById("taskCount");

  if (!tasks.length) {
    container.innerHTML = '<div class="empty-state">暂无下载任务，在上方输入地址开始</div>';
    countEl.textContent = "暂无任务";
    stopPolling();
    return;
  }

  countEl.textContent = `${tasks.length} 个任务`;

  // Check if any task is still active
  const hasActive = tasks.some(t => ["pending", "parsing", "downloading"].includes(t.status));
  if (!hasActive) stopPolling();
  else if (!pollingTimer) startPolling();

  container.innerHTML = tasks.map(t => cardHTML(t)).join("");
}

// ---------------------------------------------------------------------------
// Single card HTML
// ---------------------------------------------------------------------------
function cardHTML(t) {
  const statusLabels = {
    pending:    "等待中",
    parsing:    "解析中",
    downloading:"下载中",
    completed:  "已完成",
    failed:     "失败",
  };
  const label = statusLabels[t.status] || t.status;
  const showBar = ["downloading", "completed", "failed"].includes(t.status);
  const barCls = t.status === "completed" ? "completed" : t.status === "failed" ? "failed" : "";

  let meta = "";
  if (t.filename) meta += `<span>📁 ${esc(t.filename)}</span>`;
  if (t.duration) meta += `<span>⏱ ${esc(t.duration)}</span>`;
  if (t.current_time && t.status === "downloading") meta += `<span>▶ ${esc(t.current_time)}</span>`;
  if (t.speed && t.status === "downloading") meta += `<span>⚡ ${esc(t.speed)}</span>`;
  if (t.size) meta += `<span>💾 ${esc(t.size)}</span>`;

  let bar = "";
  if (showBar) {
    bar = `
      <div class="progress-wrap">
        <div class="progress-bar"><div class="fill ${barCls}" style="width:${t.progress}%"></div></div>
        <span class="progress-pct">${t.progress}%</span>
      </div>`;
  }

  let error = "";
  if (t.error) {
    error = `<div class="task-error">⚠️ ${esc(t.error)}</div>`;
  }

  let actions = "";
  if (t.status === "failed") {
    actions = `<button onclick="deleteTask('${t.id}')">🗑 删除</button>`;
  } else if (t.status === "completed") {
    actions = `<button onclick="deleteTask('${t.id}')">🗑 删除</button>`;
  }

  return `
    <div class="task-card" id="task-${t.id}">
      <div class="task-head">
        <span class="task-title">${esc(t.title || t.url)}</span>
        <span class="task-status ${t.status}">${label}</span>
      </div>
      ${bar}
      <div class="task-meta">${meta}</div>
      ${error}
      ${actions ? '<div class="task-actions">' + actions + '</div>' : ''}
    </div>`;
}

// ---------------------------------------------------------------------------
// Delete task
// ---------------------------------------------------------------------------
async function deleteTask(id) {
  try {
    await fetch(`/api/tasks/${id}`, { method: "DELETE" });
  } catch {}
  refresh();
}

// ---------------------------------------------------------------------------
// Clear completed
// ---------------------------------------------------------------------------
async function clearCompleted() {
  try {
    const resp = await fetch("/api/tasks");
    const tasks = await resp.json();
    for (const t of tasks) {
      if (t.status === "completed" || t.status === "failed") {
        await fetch(`/api/tasks/${t.id}`, { method: "DELETE" });
      }
    }
  } catch {}
  refresh();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
refresh();
startPolling();
