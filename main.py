"""
FastAPI application — chigua.com video downloader + site browser.
"""

import asyncio
import logging
import traceback
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("main")
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from downloader import task_manager, TaskInfo, run_download, parse_page, _fetch_page_html, safe_filename
from settings import ProxySettingsError, SettingsStore
import site_proxy

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Chigua Video Downloader", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

settings_store = SettingsStore()


def _run_in_background(coro):
    """Create a background task that logs unhandled exceptions."""

    async def _wrapper():
        try:
            await coro
        except Exception:
            logger.error("后台任务异常:\n%s", traceback.format_exc())

    asyncio.create_task(_wrapper())


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DownloadRequest(BaseModel):
    urls: str  # one URL per line
    download_dir: str = "/downloads"


class ProxySettingsIn(BaseModel):
    proxy_url: str = ""


class ProxySettingsOut(BaseModel):
    proxy_url: str


class TaskOut(BaseModel):
    id: str
    url: str
    status: str
    title: str
    filename: str
    progress: float
    speed: str
    size: str
    duration: str
    current_time: str
    error: str
    download_dir: str

    @classmethod
    def from_task(cls, t: TaskInfo) -> "TaskOut":
        return cls(
            id=t.id,
            url=t.url,
            status=t.status,
            title=t.title,
            filename=t.filename,
            progress=round(t.progress, 1),
            speed=t.speed,
            size=t.size,
            duration=t.duration,
            current_time=t.current_time,
            error=t.error,
            download_dir=t.download_dir,
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def browse_home():
    """Serve the browse SPA for homepage."""
    return FileResponse("static/browse.html")


@app.get("/category/{slug}")
async def browse_category(slug: str):
    """Serve the browse SPA for category pages."""
    return FileResponse("static/browse.html")


@app.get("/archives/{article_id}")
async def browse_article(article_id: str):
    """Serve the browse SPA for article pages."""
    return FileResponse("static/browse.html")


@app.get("/search")
async def browse_search():
    """Serve the browse SPA for search pages."""
    return FileResponse("static/browse.html")


@app.get("/download")
async def download_page():
    """Download manager page."""
    return FileResponse("static/index.html")


# ---------------------------------------------------------------------------
# Site proxy API
# ---------------------------------------------------------------------------

@app.get("/api/site/categories")
async def site_categories():
    """Return all site categories (matching chigua.com navigation)."""
    return await site_proxy.get_categories()


@app.get("/api/site/feed")
async def site_feed(page: int = Query(1)):
    """Homepage article feed (RSS page 1, HTML scrape for pagination)."""
    proxy_url = settings_store.load().proxy_url
    result = await site_proxy.get_homepage_feed(proxy_url, page)
    return {
        "items": [_article_item_to_dict(i) for i in result.items],
        "page": result.page,
        "has_next": result.has_next,
        "next_page": result.next_page,
    }


@app.get("/api/site/category/{slug}")
async def site_category(slug: str, page: int = Query(1)):
    """Paginated article list for a category (scraped from HTML)."""
    proxy_url = settings_store.load().proxy_url
    result = await site_proxy.get_category_page(slug, page, proxy_url)
    return {
        "items": [_article_item_to_dict(i) for i in result.items],
        "page": result.page,
        "has_next": result.has_next,
        "next_page": result.next_page,
    }


@app.get("/api/site/article/{article_id}")
async def site_article(article_id: str):
    """Article detail with video URLs and sanitized content."""
    proxy_url = settings_store.load().proxy_url
    detail = await site_proxy.get_article_detail(article_id, proxy_url)
    return {
        "id": detail.id,
        "title": detail.title,
        "url": detail.url,
        "author": detail.author,
        "date": detail.date,
        "categories": detail.categories,
        "thumbnail": detail.thumbnail,
        "videos": detail.videos,
        "content_html": detail.content_html,
        "related": [_article_item_to_dict(r) for r in detail.related],
    }


@app.get("/api/site/search")
async def site_search(q: str = Query("")):
    """Search articles."""
    if not q.strip():
        return {"items": []}
    proxy_url = settings_store.load().proxy_url
    items = await site_proxy.search_articles(q.strip(), proxy_url)
    return {"items": [_article_item_to_dict(i) for i in items]}


@app.get("/api/site/image-proxy")
async def site_image_proxy(url: str = Query("")):
    """Proxy an image to avoid CORS/referrer issues (fallback for blocked CDNs)."""
    if not url:
        raise HTTPException(400, "url is required")
    try:
        # Fetch directly, don't use the configured proxy (which may not exist)
        content = await site_proxy.get_image_proxy(url, "")
        ext = url.split(".")[-1].split("?")[0].lower()
        ct_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                   "webp": "image/webp", "gif": "image/gif"}
        content_type = ct_map.get(ext, "image/jpeg")
        return Response(content=content, media_type=content_type)
    except Exception as e:
        raise HTTPException(500, f"Image proxy failed: {e}")


@app.post("/api/site/download")
async def site_download(req: DownloadRequest):
    """Download from browse page — same as /api/tasks but returns simpler."""
    urls = [u.strip() for u in req.urls.split("\n") if u.strip()]
    if not urls:
        raise HTTPException(400, "请至少输入一个地址")

    download_dir = req.download_dir.strip() or "/downloads"
    try:
        Path(download_dir).mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fallback for non-Docker environments
        download_dir = "./downloads"
        Path(download_dir).mkdir(parents=True, exist_ok=True)

    proxy_url = settings_store.load().proxy_url

    created = 0
    for url in urls:
        videos: list[dict] = []
        try:
            html = await _fetch_page_html(url, proxy_url)
            videos = parse_page(html)
        except Exception:
            pass

        if not videos:
            t = task_manager.create(url, download_dir, proxy_url)
            asyncio.create_task(run_download(t))
            created += 1
        else:
            for info in videos:
                t = task_manager.create(
                    url, download_dir, proxy_url,
                    video_url=info["url"], video_title=info["title"],
                )
                t.title = info["title"]
                t.filename = safe_filename(info["title"]) + ".mp4"
                asyncio.create_task(run_download(t))
                created += 1

    return {"ok": True, "tasks_created": created}


def _article_item_to_dict(item) -> dict:
    """Convert ArticleItem to dict for JSON response."""
    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "thumbnail": item.thumbnail,
        "author": item.author,
        "date": item.date,
        "categories": item.categories,
    }


@app.post("/api/tasks", response_model=list[TaskOut])
async def create_tasks(req: DownloadRequest):
    """Submit one or more URLs for download (one task per video found)."""
    urls = [u.strip() for u in req.urls.split("\n") if u.strip()]
    if not urls:
        raise HTTPException(400, "请至少输入一个地址")

    download_dir = req.download_dir.strip() or "/downloads"
    Path(download_dir).mkdir(parents=True, exist_ok=True)

    proxy_url = settings_store.load().proxy_url
    tasks: list[TaskOut] = []

    for url in urls:
        # Try to pre-resolve videos from the page
        videos: list[dict] = []
        try:
            html = await _fetch_page_html(url, proxy_url)
            videos = parse_page(html)
        except Exception as e:
            logger.warning("端点预解析页面失败 [%s]: %s", url, type(e).__name__)

        if not videos:
            # No videos found or fetch failed — create one task; run_download
            # will fetch the page again and report the error.
            t = task_manager.create(url, download_dir, proxy_url)
            tasks.append(TaskOut.from_task(t))
            asyncio.create_task(run_download(t))
        else:
            for info in videos:
                t = task_manager.create(
                    url,
                    download_dir,
                    proxy_url,
                    video_url=info["url"],
                    video_title=info["title"],
                )
                t.title = info["title"]
                t.filename = safe_filename(info["title"]) + ".mp4"
                tasks.append(TaskOut.from_task(t))
                _run_in_background(run_download(t))

    return tasks


@app.get("/api/settings/proxy", response_model=ProxySettingsOut)
async def get_proxy_settings():
    settings = settings_store.load()
    return ProxySettingsOut(proxy_url=settings.proxy_url)


@app.post("/api/settings/proxy", response_model=ProxySettingsOut)
async def save_proxy_settings(req: ProxySettingsIn):
    try:
        settings = settings_store.save_proxy(req.proxy_url)
    except ProxySettingsError as e:
        raise HTTPException(400, str(e)) from e

    return ProxySettingsOut(proxy_url=settings.proxy_url)


@app.get("/api/tasks", response_model=list[TaskOut])
async def list_tasks():
    """Return all tasks (sorted newest-first)."""
    all_tasks = task_manager.list_all()
    all_tasks.sort(key=lambda t: t.id, reverse=True)
    return [TaskOut.from_task(t) for t in all_tasks]


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """Remove a task from the list (and cancel if downloading)."""
    t = task_manager.get(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    task_manager.delete(task_id)
    return {"ok": True}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Static files (must be last)
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")
