// ---------------------------------------------------------------------------
// Chigua Video Downloader — frontend
// ---------------------------------------------------------------------------

let pollingTimer = null;
const PROXY_STORAGE_KEY = "chigua.proxyUrl";

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
    await saveProxySettings({ silent: true });
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
    const tasks = await resp.json();
    document.getElementById("urls").value = "";
    const inputCount = urls.split("\n").filter(l => l.trim()).length;
    if (tasks.length > inputCount) {
      setSubmitFeedback(`发现 ${tasks.length} 个视频，已全部添加`);
    } else {
      setSubmitFeedback(`已添加 ${tasks.length} 个任务`);
    }
    startPolling();
  } catch (e) {
    alert(formatSubmitError(e));
  } finally {
    btn.disabled = false;
    btn.textContent = "⬇️ 开始下载";
  }
}

// ---------------------------------------------------------------------------
// Proxy settings
// ---------------------------------------------------------------------------
async function loadProxySettings() {
  const input = document.getElementById("proxyUrl");
  const cached = localStorage.getItem(PROXY_STORAGE_KEY) || "";
  input.value = cached;

  const resp = await fetch("/api/settings/proxy");
  if (!resp.ok) throw new Error(await readError(resp));

  const data = await resp.json();
  input.value = data.proxy_url || "";
  localStorage.setItem(PROXY_STORAGE_KEY, input.value);
}

async function saveProxySettings(options = {}) {
  try {
    const input = document.getElementById("proxyUrl");
    const proxyUrl = input.value.trim();
    const resp = await fetch("/api/settings/proxy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proxy_url: proxyUrl }),
    });

    if (!resp.ok) throw new Error("代理保存失败: " + (await readError(resp)));

    const data = await resp.json();
    input.value = data.proxy_url || "";
    localStorage.setItem(PROXY_STORAGE_KEY, input.value);
    if (!options.silent) setProxyStatus(input.value ? "代理已保存" : "代理已清空");
  } catch (e) {
    if (!options.silent) {
      setProxyStatus(e.message);
      return;
    }
    throw e;
  }
}

function bindProxyInput() {
  document.getElementById("proxyUrl").addEventListener("input", e => {
    localStorage.setItem(PROXY_STORAGE_KEY, e.target.value.trim());
    setProxyStatus("");
  });
}

function setProxyStatus(message) {
  document.getElementById("proxyStatus").textContent = message;
}

function setSubmitFeedback(message) {
  const el = document.getElementById("submitFeedback");
  el.textContent = message;
  el.style.display = message ? "" : "none";
  if (message) setTimeout(() => { el.textContent = ""; el.style.display = "none"; }, 4000);
}

async function readError(resp) {
  try {
    const err = await resp.json();
    return err.detail || resp.statusText;
  } catch {
    return resp.statusText;
  }
}

function formatSubmitError(error) {
  const message = error.message || String(error);
  if (message.startsWith("代理保存失败")) return message;
  return "网络错误: " + message;
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
bindProxyInput();
loadProxySettings().catch(e => setProxyStatus("代理加载失败: " + e.message));
refresh();
startPolling();
