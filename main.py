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

from downloader import task_manager, TaskInfo, run_download

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

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DownloadRequest(BaseModel):
    urls: str  # one URL per line
    download_dir: str = "/downloads"


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
    """Submit one or more URLs for download."""
    urls = [u.strip() for u in req.urls.split("\n") if u.strip()]
    if not urls:
        raise HTTPException(400, "请至少输入一个地址")

    download_dir = req.download_dir.strip() or "/downloads"
    Path(download_dir).mkdir(parents=True, exist_ok=True)

    tasks: list[TaskOut] = []
    for url in urls:
        t = task_manager.create(url, download_dir)
        tasks.append(TaskOut.from_task(t))
        # Fire-and-forget background download
        asyncio.create_task(run_download(t))

    return tasks


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
