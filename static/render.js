// ---------------------------------------------------------------------------
// Task list rendering
// ---------------------------------------------------------------------------

const TASK_STATUS_LABELS = {
  pending: "等待中",
  parsing: "解析中",
  downloading: "下载中",
  completed: "已完成",
  failed: "失败",
};

const PROGRESS_STATUSES = new Set(["downloading", "completed", "failed"]);
const ACTION_STATUSES = new Set(["completed", "failed"]);
const PROGRESS_CLASS_BY_STATUS = {
  completed: "completed",
  failed: "failed",
};

function syncTaskCards(container, tasks) {
  removeTaskPlaceholders(container);

  const taskIds = new Set();
  tasks.forEach((task, index) => {
    taskIds.add(task.id);
    const card = upsertTaskCard(container, task, index);
    updateTaskCard(card, task);
  });
  removeStaleTaskCards(container, taskIds);
}

function removeTaskPlaceholders(container) {
  Array.from(container.children).forEach(child => {
    if (!child.classList.contains("task-card")) child.remove();
  });
}

function upsertTaskCard(container, task, index) {
  let card = document.getElementById(taskElementId(task.id));
  if (!card) {
    container.insertAdjacentHTML("beforeend", cardHTML(task));
    card = document.getElementById(taskElementId(task.id));
  }
  if (!card) throw new Error(`任务卡片创建失败: ${task.id}`);

  const expected = container.children[index] || null;
  if (card !== expected) container.insertBefore(card, expected);
  return card;
}

function removeStaleTaskCards(container, taskIds) {
  Array.from(container.children).forEach(card => {
    if (!card.classList.contains("task-card")) return;
    if (!taskIds.has(card.dataset.taskId)) card.remove();
  });
}

function updateTaskCard(card, task) {
  const status = taskStatus(task.status);
  setRoleText(card, "title", task.title || task.url);

  const statusEl = roleElement(card, "status");
  statusEl.textContent = status.label;
  statusEl.className = `task-status ${task.status}`;

  renderProgress(card, task, status);
  roleElement(card, "meta").innerHTML = metaHTML(task);
  renderError(card, task);
  renderActions(card, task);
}

function renderProgress(card, task, status) {
  const progress = card.querySelector('[data-role="progress"]');
  if (!status.showProgress) {
    if (progress) progress.remove();
    return;
  }
  if (!progress) {
    roleElement(card, "head").insertAdjacentHTML("afterend", progressHTML(task, status.progressClass));
    return;
  }
  updateProgress(progress, task, status.progressClass);
}

function updateProgress(progress, task, progressClass) {
  const fill = roleElement(progress, "progress-fill");
  fill.className = progressFillClass(progressClass);
  fill.style.width = `${task.progress}%`;
  setRoleText(progress, "progress-pct", `${task.progress}%`);
}

function renderError(card, task) {
  const error = card.querySelector('[data-role="error"]');
  if (!task.error) {
    if (error) error.remove();
    return;
  }
  if (error) {
    error.textContent = `⚠️ ${task.error}`;
    return;
  }
  roleElement(card, "meta").insertAdjacentHTML("afterend", errorHTML(task.error));
}

function renderActions(card, task) {
  const actions = card.querySelector('[data-role="actions"]');
  if (!ACTION_STATUSES.has(task.status)) {
    if (actions) actions.remove();
    return;
  }
  if (actions) return;

  const anchor = card.querySelector('[data-role="error"]') || roleElement(card, "meta");
  anchor.insertAdjacentHTML("afterend", actionsHTML(task));
}

function cardHTML(task) {
  const status = taskStatus(task.status);
  const progress = status.showProgress ? progressHTML(task, status.progressClass) : "";
  const error = task.error ? errorHTML(task.error) : "";
  const actions = ACTION_STATUSES.has(task.status) ? actionsHTML(task) : "";

  return `
    <div class="task-card" id="${escAttr(taskElementId(task.id))}" data-task-id="${escAttr(task.id)}">
      <div class="task-head" data-role="head">
        <span class="task-title" data-role="title">${esc(task.title || task.url)}</span>
        <span class="task-status ${task.status}" data-role="status">${esc(status.label)}</span>
      </div>
      ${progress}
      <div class="task-meta" data-role="meta">${metaHTML(task)}</div>
      ${error}
      ${actions}
    </div>`;
}

function progressHTML(task, progressClass) {
  return `
      <div class="progress-wrap" data-role="progress">
        <div class="progress-bar">
          <div class="${progressFillClass(progressClass)}" data-role="progress-fill" style="width:${task.progress}%"></div>
        </div>
        <span class="progress-pct" data-role="progress-pct">${task.progress}%</span>
      </div>`;
}

function metaHTML(task) {
  let meta = "";
  if (task.filename) meta += `<span>📁 ${esc(task.filename)}</span>`;
  if (task.duration) meta += `<span>⏱ ${esc(task.duration)}</span>`;
  if (task.current_time && task.status === "downloading") meta += `<span>▶ ${esc(task.current_time)}</span>`;
  if (task.speed && task.status === "downloading") meta += `<span>⚡ ${esc(task.speed)}</span>`;
  if (task.size) meta += `<span>💾 ${esc(task.size)}</span>`;
  return meta;
}

function errorHTML(message) {
  return `<div class="task-error" data-role="error">⚠️ ${esc(message)}</div>`;
}

function actionsHTML(task) {
  return `
      <div class="task-actions" data-role="actions">
        <button data-task-id="${escAttr(task.id)}" onclick="deleteTask(this.dataset.taskId)">🗑 删除</button>
      </div>`;
}

function taskStatus(status) {
  return {
    label: TASK_STATUS_LABELS[status] || status,
    showProgress: PROGRESS_STATUSES.has(status),
    progressClass: PROGRESS_CLASS_BY_STATUS[status] || "",
  };
}

function progressFillClass(progressClass) {
  return ["fill", progressClass].filter(Boolean).join(" ");
}

function taskElementId(taskId) {
  return `task-${taskId}`;
}

function setRoleText(scope, role, text) {
  roleElement(scope, role).textContent = text;
}

function roleElement(scope, role) {
  const element = scope.querySelector(`[data-role="${role}"]`);
  if (!element) throw new Error(`任务卡片节点缺失: ${role}`);
  return element;
}

function escAttr(value) {
  return esc(value).replace(/"/g, "&quot;");
}

function esc(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}
