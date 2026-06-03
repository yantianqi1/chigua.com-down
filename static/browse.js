// =====================================================================
// Chigua Browse — Ink-Wash Masonry SPA
// =====================================================================

// ---- State ----
const state = {
  view: "feed",        // "feed" | "detail" | "search"
  currentCategory: null, // null = homepage
  currentArticleId: null,
  currentSearchQuery: "",
  feedPage: 1,
  feedHasNext: false,
  feedNextPage: null,
  isLoading: false,
  detailData: null,
};

// ---- Init ----
document.addEventListener("DOMContentLoaded", () => {
  loadCategories();
  handleRoute();
  pollDownloadBadge();
  setInterval(pollDownloadBadge, 3000);

  // Search toggle
  document.getElementById("searchToggle").addEventListener("click", toggleSearch);
  document.getElementById("searchClose").addEventListener("click", toggleSearch);
  document.getElementById("searchSubmit").addEventListener("click", doSearch);
  document.getElementById("searchInput").addEventListener("keydown", e => {
    if (e.key === "Enter") doSearch();
  });

  // Popstate for browser back/forward
  window.addEventListener("popstate", handleRoute);
});

// ---- Routing ----
function handleRoute() {
  const path = window.location.pathname;
  const params = new URLSearchParams(window.location.search);

  if (path.startsWith("/archives/")) {
    const id = path.split("/")[2];
    state.currentArticleId = id;
    showDetail(id);
  } else if (path.startsWith("/category/")) {
    const slug = path.split("/")[2];
    state.currentCategory = slug;
    state.currentSearchQuery = "";
    showCategoryFeed(slug);
  } else if (path === "/search" || path.startsWith("/search")) {
    const q = params.get("q") || "";
    if (q) {
      state.currentSearchQuery = q;
      doSearchFromQuery(q);
    } else {
      showFeed();
    }
  } else {
    // Homepage
    state.currentCategory = null;
    state.currentSearchQuery = "";
    showFeed();
  }
}

function navigate(path) {
  window.history.pushState({}, "", path);
  handleRoute();
}

// ---- Category Nav ----
async function loadCategories() {
  const container = document.getElementById("navCategories");
  try {
    const resp = await fetch("/api/site/categories");
    const cats = await resp.json();
    renderCategoryChips(container, cats);
  } catch (e) {
    console.error("Failed to load categories", e);
  }
}

function renderCategoryChips(container, cats) {
  container.innerHTML = cats.map(c => {
    const isActive = state.currentCategory === c.slug;
    return `<a href="/category/${c.slug}" class="cat-chip${isActive ? ' active' : ''}"
               data-link="/category/${c.slug}">${c.name}</a>`;
  }).join("");

  // Bind click handlers
  container.querySelectorAll(".cat-chip").forEach(chip => {
    chip.addEventListener("click", e => {
      e.preventDefault();
      const link = chip.dataset.link;
      // Update active state
      container.querySelectorAll(".cat-chip").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      navigate(link);
    });
  });

  // Also mark homepage chip
  updateActiveChip();
}

function updateActiveChip() {
  const chips = document.querySelectorAll(".cat-chip");
  chips.forEach(c => {
    c.classList.remove("active");
    if (!state.currentCategory && c.dataset.link === "/") {
      c.classList.add("active");
    }
    if (state.currentCategory && c.dataset.link === `/category/${state.currentCategory}`) {
      c.classList.add("active");
    }
  });
}

// ---- Feed Views ----
async function showFeed() {
  showView("feed");
  state.view = "feed";
  state.feedPage = 1;
  state.currentCategory = null;
  document.getElementById("feedTitle").textContent = "🔥 最新吃瓜";
  document.getElementById("feedSubtitle").textContent = "";
  updateActiveChip();

  const grid = document.getElementById("masonryGrid");
  grid.innerHTML = "";
  showFeedLoading(true);

  try {
    const data = await fetchJSON(`/api/site/feed?page=1`);
    state.feedHasNext = data.has_next;
    state.feedNextPage = data.next_page;
    renderCards(grid, data.items);
    updateLoadMoreBtn();
  } catch (e) {
    grid.innerHTML = `<div class="empty-state">加载失败，请检查网络连接</div>`;
  } finally {
    showFeedLoading(false);
  }
}

async function showCategoryFeed(slug) {
  showView("feed");
  state.view = "feed";
  state.feedPage = 1;
  state.currentCategory = slug;

  const catName = findCategoryName(slug);
  document.getElementById("feedTitle").textContent = catName || slug;
  document.getElementById("feedSubtitle").textContent = "";
  updateActiveChip();

  const grid = document.getElementById("masonryGrid");
  grid.innerHTML = "";
  showFeedLoading(true);

  try {
    const data = await fetchJSON(`/api/site/category/${slug}?page=1`);
    state.feedHasNext = data.has_next;
    state.feedNextPage = data.next_page;
    renderCards(grid, data.items);
    updateLoadMoreBtn();
  } catch (e) {
    grid.innerHTML = `<div class="empty-state">加载失败，请检查网络连接</div>`;
  } finally {
    showFeedLoading(false);
  }
}

async function loadMore() {
  if (state.isLoading || !state.feedHasNext) return;
  state.isLoading = true;
  const btn = document.getElementById("loadMoreBtn");
  btn.disabled = true;
  btn.textContent = "加载中…";
  showFeedLoading(true);

  try {
    const nextPage = state.feedNextPage || (state.feedPage + 1);
    let url;
    if (state.currentCategory) {
      url = `/api/site/category/${state.currentCategory}?page=${nextPage}`;
    } else {
      // Fallback: scrape category page for pagination
      url = `/api/site/category/wpcz?page=${nextPage}`; // won't be used for feed
      // Actually for homepage we use RSS which doesn't paginate well
      // Instead try scraping a popular category
      url = `/api/site/category/rdsj?page=${nextPage}`;
    }
    const data = await fetchJSON(url);
    state.feedPage = nextPage;
    state.feedHasNext = data.has_next;
    state.feedNextPage = data.next_page;

    const grid = document.getElementById("masonryGrid");
    renderCards(grid, data.items);
    updateLoadMoreBtn();
  } catch (e) {
    console.error("Load more failed", e);
  } finally {
    state.isLoading = false;
    btn.disabled = false;
    btn.textContent = "加载更多";
    showFeedLoading(false);
  }
}

function updateLoadMoreBtn() {
  const wrap = document.getElementById("loadMoreWrap");
  if (state.feedHasNext) {
    wrap.style.display = "block";
  } else {
    wrap.style.display = "none";
  }
}

// ---- Article Detail ----
async function showDetail(id) {
  showView("detail");
  state.view = "detail";
  state.currentArticleId = id;

  const container = document.getElementById("detailContent");
  container.innerHTML = `<div class="loading-indicator"><span class="spinner"></span>加载中…</div>`;

  try {
    const data = await fetchJSON(`/api/site/article/${id}`);
    state.detailData = data;
    renderDetail(container, data);
  } catch (e) {
    container.innerHTML = `<div class="empty-state">加载失败: ${e.message}</div>`;
  }
}

function renderDetail(container, data) {
  const catTags = (data.categories || []).map(c =>
    `<a href="/category/${slugify(c)}" class="cat-tag" onclick="event.preventDefault();navigate('/category/${slugify(c)}')">${esc(c)}</a>`
  ).join("");

  const videoList = data.videos && data.videos.length > 1
    ? `<div class="sidebar-section">
        <h3>📹 本页视频 (${data.videos.length})</h3>
        ${data.videos.map((v, i) => `
          <div class="video-list-item" onclick="switchVideo(${i})" data-video-idx="${i}">
            <div class="thumb" style="background:rgba(26,26,26,.06);display:grid;place-items:center;">▶</div>
            <div class="info">${esc(v.title || data.title)}</div>
          </div>
        `).join("")}
      </div>`
    : "";

  const relatedHTML = data.related && data.related.length
    ? `<div class="sidebar-section">
        <h3>🔥 相关推荐</h3>
        ${data.related.slice(0, 5).map(r => `
          <div class="video-list-item" onclick="navigate('${r.url}')">
            <img class="thumb" src="${r.thumbnail ? `/api/site/image-proxy?url=${encodeURIComponent(r.thumbnail)}` : ''}" alt="" loading="lazy">
            <div class="info">${esc(r.title)}</div>
          </div>
        `).join("")}
      </div>`
    : "";

  container.innerHTML = `
    <div class="detail-layout">
      <div class="detail-main">
        <div class="player-wrap" id="playerWrap"></div>
        <div class="detail-header">
          <h1>${esc(data.title)}</h1>
          <div class="detail-meta">
            ${data.author ? `<span>✍ ${esc(data.author)}</span>` : ""}
            ${data.date ? `<span>📅 ${esc(data.date)}</span>` : ""}
          </div>
          <div class="detail-cats">${catTags}</div>
        </div>
        <div class="download-actions">
          <button class="dl-btn" onclick="downloadVideo()" id="dlBtn">
            ⬇️ 下载此视频
          </button>
          <button class="dl-btn" style="background:var(--ink-heavy);border-color:rgba(51,51,51,.3);font-size:.9rem;"
                  onclick="copyVideoUrl()">
            📋 复制视频地址
          </button>
        </div>
        ${data.content_html ? `
          <div class="article-body">${data.content_html}</div>
        ` : ""}
        ${data.videos && data.videos.length > 1 ? `
          <div class="sidebar-section" style="margin-top:1rem;">
            <h3>📹 本页其他视频</h3>
            ${data.videos.map((v, i) => `
              <div class="video-list-item" onclick="switchVideo(${i})" data-video-idx="${i}">
                <div class="thumb" style="background:rgba(26,26,26,.06);display:grid;place-items:center;">▶</div>
                <div class="info">${esc(v.title || data.title)}</div>
              </div>
            `).join("")}
          </div>
        ` : ""}
      </div>
      <div class="detail-sidebar">
        ${videoList}
        ${relatedHTML}
      </div>
    </div>
  `;

  // Init player
  initPlayer(data);

  // Scroll to top
  window.scrollTo(0, 0);
}

// ---- DPlayer ----
let currentPlayer = null;
let currentVideoIdx = 0;

function initPlayer(data) {
  if (currentPlayer) {
    currentPlayer.destroy();
    currentPlayer = null;
  }

  if (!data.videos || !data.videos.length) {
    document.getElementById("playerWrap").innerHTML =
      `<div style="padding:3rem;text-align:center;color:var(--ink-clear);background:rgba(26,26,26,.03);border-radius:8px;">
        未找到可播放视频
      </div>`;
    return;
  }

  currentVideoIdx = 0;
  const video = data.videos[0];

  currentPlayer = new DPlayer({
    container: document.getElementById("playerWrap"),
    autoplay: false,
    theme: "#C41E3A",
    loop: false,
    lang: "zh-cn",
    screenshot: false,
    hotkey: true,
    preload: "metadata",
    volume: 0.7,
    video: {
      url: video.url,
      type: video.type || "hls",
    },
  });
}

function switchVideo(idx) {
  if (!state.detailData || !state.detailData.videos) return;
  const videos = state.detailData.videos;
  if (idx < 0 || idx >= videos.length) return;

  currentVideoIdx = idx;
  const video = videos[idx];

  if (currentPlayer) {
    currentPlayer.destroy();
    currentPlayer = null;
  }

  currentPlayer = new DPlayer({
    container: document.getElementById("playerWrap"),
    autoplay: true,
    theme: "#C41E3A",
    loop: false,
    lang: "zh-cn",
    screenshot: false,
    hotkey: true,
    preload: "metadata",
    volume: 0.7,
    video: {
      url: video.url,
      type: video.type || "hls",
    },
  });

  // Update sidebar active
  document.querySelectorAll("[data-video-idx]").forEach(el => {
    el.style.borderColor = el.dataset.videoIdx === String(idx)
      ? "rgba(196, 30, 58, .35)" : "transparent";
  });

  toast(`切换到: ${video.title || `视频 ${idx + 1}`}`);
}

// ---- Download ----
async function downloadVideo() {
  if (!state.detailData) return;
  const btn = document.getElementById("dlBtn");
  const origText = btn.textContent;
  btn.textContent = "⏳ 提交中…";
  btn.classList.add("downloading");

  try {
    const resp = await fetch("/api/site/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        urls: `https://chigua.com/archives/${state.detailData.id}/`,
        download_dir: "/downloads",
      }),
    });
    const result = await resp.json();
    if (result.ok) {
      toast(`✅ 已添加 ${result.tasks_created} 个下载任务`);
      pollDownloadBadge();
    }
  } catch (e) {
    toast("下载提交失败: " + e.message);
  } finally {
    btn.textContent = origText;
    btn.classList.remove("downloading");
  }
}

function copyVideoUrl() {
  if (!state.detailData || !state.detailData.videos || !state.detailData.videos.length) {
    toast("没有可复制的视频地址");
    return;
  }
  const urls = state.detailData.videos.map(v => v.url).join("\n");
  navigator.clipboard.writeText(urls).then(
    () => toast(`✅ 已复制 ${state.detailData.videos.length} 个视频地址`),
    () => toast("复制失败，请手动复制")
  );
}

// ---- Search ----
function toggleSearch() {
  const bar = document.getElementById("searchBar");
  const input = document.getElementById("searchInput");
  if (bar.style.display === "none") {
    bar.style.display = "flex";
    input.focus();
  } else {
    bar.style.display = "none";
    input.value = "";
  }
}

function doSearch() {
  const q = document.getElementById("searchInput").value.trim();
  if (!q) return;
  document.getElementById("searchBar").style.display = "none";
  navigate(`/search?q=${encodeURIComponent(q)}`);
}

async function doSearchFromQuery(q) {
  showView("search");
  state.view = "search";
  state.currentSearchQuery = q;
  document.getElementById("searchTitle").textContent = `搜索结果: ${q}`;

  const grid = document.getElementById("searchGrid");
  grid.innerHTML = `<div class="loading-indicator"><span class="spinner"></span>搜索中…</div>`;

  try {
    const data = await fetchJSON(`/api/site/search?q=${encodeURIComponent(q)}`);
    grid.innerHTML = "";
    if (!data.items || data.items.length === 0) {
      grid.innerHTML = `<div class="empty-state">没有找到相关内容</div>`;
    } else {
      renderCards(grid, data.items);
    }
  } catch (e) {
    grid.innerHTML = `<div class="empty-state">搜索失败: ${e.message}</div>`;
  }
}

// ---- Download Badge ----
async function pollDownloadBadge() {
  try {
    const resp = await fetch("/api/tasks");
    const tasks = await resp.json();
    const active = tasks.filter(t =>
      ["pending", "parsing", "downloading"].includes(t.status)
    );
    const badge = document.getElementById("downloadBadge");
    if (active.length > 0) {
      badge.textContent = active.length;
      badge.style.display = "grid";
    } else {
      badge.style.display = "none";
    }
  } catch (e) { /* ignore */ }
}

// ---- Navigation ----
function goBack() {
  if (state.view === "detail") {
    if (state.currentCategory) {
      navigate(`/category/${state.currentCategory}`);
    } else if (state.currentSearchQuery) {
      navigate(`/search?q=${encodeURIComponent(state.currentSearchQuery)}`);
    } else {
      navigate("/");
    }
  } else if (state.view === "search") {
    navigate("/");
  }
}

function showView(name) {
  document.getElementById("viewFeed").style.display = name === "feed" ? "" : "none";
  document.getElementById("viewDetail").style.display = name === "detail" ? "" : "none";
  document.getElementById("viewSearch").style.display = name === "search" ? "" : "none";
}

function showFeedLoading(show) {
  document.getElementById("feedLoading").style.display = show ? "" : "none";
}

// ---- Masonry Cards ----
function renderCards(grid, items) {
  if (!items || !items.length) return;

  const fragment = document.createDocumentFragment();
  items.forEach(item => {
    const card = createCard(item);
    fragment.appendChild(card);
  });
  grid.appendChild(fragment);
}

function createCard(item) {
  const div = document.createElement("div");
  div.className = "masonry-card";
  div.addEventListener("click", () => navigate(item.url));

  const imgSrc = item.thumbnail
    ? `/api/site/image-proxy?url=${encodeURIComponent(item.thumbnail)}`
    : "";

  const catTags = (item.categories || []).slice(0, 2).map(c =>
    `<span class="cat-tag">${esc(c)}</span>`
  ).join("");

  div.innerHTML = `
    <div class="card-img-wrap">
      ${imgSrc ? `<img src="${imgSrc}" alt="" loading="lazy" onerror="this.parentElement.style.minHeight='120px'">` : ""}
      <div class="card-play-icon">▶</div>
    </div>
    <div class="card-body">
      <div class="card-title">${esc(item.title)}</div>
      <div class="card-meta">
        ${item.author ? `<span>✍ ${esc(item.author)}</span>` : ""}
        ${item.date ? `<span>📅 ${esc(item.date)}</span>` : ""}
      </div>
      ${catTags ? `<div class="card-cats">${catTags}</div>` : ""}
    </div>
  `;
  return div;
}

// ---- Utilities ----
async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

function esc(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function findCategoryName(slug) {
  // Quick lookup from the rendered nav
  const chips = document.querySelectorAll(".cat-chip");
  for (const chip of chips) {
    if (chip.dataset.link === `/category/${slug}`) {
      return chip.textContent.trim();
    }
  }
  return slug;
}

function slugify(name) {
  // Map category name to slug for known categories
  const known = {
    "今日吃瓜": "wpcz", "学生校园": "xsxy", "网红黑料": "whhl",
    "热门大瓜": "rdsj", "吃瓜榜单": "mrdg", "必看大瓜": "bkdg",
    "看片娱乐": "ysyl", "每日大赛": "mrds", "伦理道德": "lldd",
    "网黄合集": "whhj", "国产剧情": "gcjq", "探花精选": "thjx",
    "免费短剧": "cbdj", "骚男骚女": "snsn", "明星黑料": "whmx",
    "海外吃瓜": "hwcg", "人人吃瓜": "rrcg", "领导干部": "ldcg",
    "世界杯专栏": "sjb", "吃瓜看戏": "qubk", "擦边聊骚": "dcbq",
    "51涨知识": "zzs", "吃瓜新闻": "cgxw", "51品茶": "51by",
    "51剧场": "51djc", "原创博主": "yczq",
  };
  return known[name] || name;
}

function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(el._timeout);
  el._timeout = setTimeout(() => el.classList.remove("show"), 2500);
}

// ---- Keyboard shortcuts ----
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    if (document.getElementById("searchBar").style.display !== "none") {
      toggleSearch();
    } else if (state.view === "detail") {
      goBack();
    }
  }
  if ((e.ctrlKey || e.metaKey) && e.key === "k") {
    e.preventDefault();
    toggleSearch();
  }
});
