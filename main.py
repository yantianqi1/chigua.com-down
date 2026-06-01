"""
FastAPI application — chigua.com video downloader.
"""

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from downloader import task_manager, TaskInfo, run_download, parse_page, _fetch_page_html, safe_filename
from settings import ProxySettingsError, SettingsStore

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
async def index():
    return FileResponse("static/index.html")


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
        except Exception:
            pass  # fall through — run_download will retry

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
                asyncio.create_task(run_download(t))

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
