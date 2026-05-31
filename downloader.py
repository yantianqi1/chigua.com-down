"""
Download engine: parses chigua.com pages and downloads videos via ffmpeg.
"""

import asyncio
import json
import re
import html as html_mod
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import httpx


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class TaskInfo:
    id: str
    url: str
    status: str = "pending"  # pending | parsing | downloading | completed | failed
    title: str = ""
    filename: str = ""
    progress: float = 0.0
    speed: str = ""
    size: str = ""
    duration: str = ""
    current_time: str = ""
    error: str = ""
    download_dir: str = "/downloads"
    _cancel: bool = field(default=False, repr=False)


# ---------------------------------------------------------------------------
# Task manager (in-memory)
# ---------------------------------------------------------------------------

class TaskManager:
    def __init__(self):
        self._tasks: dict[str, TaskInfo] = {}

    def create(self, url: str, download_dir: str) -> TaskInfo:
        t = TaskInfo(id=uuid.uuid4().hex[:8], url=url, download_dir=download_dir)
        self._tasks[t.id] = t
        return t

    def get(self, task_id: str) -> Optional[TaskInfo]:
        return self._tasks.get(task_id)

    def list_all(self) -> list[TaskInfo]:
        return list(self._tasks.values())

    def delete(self, task_id: str):
        t = self._tasks.get(task_id)
        if t:
            t._cancel = True
        self._tasks.pop(task_id, None)


task_manager = TaskManager()


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def parse_page(html: str) -> Optional[dict]:
    """Extract video m3u8 URL and title from chigua.com page HTML."""

    def _extract(cfg_str: str) -> Optional[dict]:
        cfg_str = html_mod.unescape(cfg_str)
        try:
            config = json.loads(cfg_str)
            url = config["video"]["url"]
        except (KeyError, json.JSONDecodeError):
            return None

        # title: prefer data-video_title, then <h1>, then <title>
        title = "video"
        tm = re.search(r'data-video_title="([^"]*)"', html)
        if tm:
            title = html_mod.unescape(tm.group(1))
        else:
            hm = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
            if hm:
                title = re.sub(r"<[^>]+>", "", html_mod.unescape(hm.group(1))).strip()
            else:
                ttm = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
                if ttm:
                    title = re.sub(r"<[^>]+>", "", html_mod.unescape(ttm.group(1))).strip()
                    title = title.split("|")[0].strip()
        return {"url": url, "title": title}

    # Try single-quoted data-config (most common)
    for cfg in re.findall(r"data-config='([^']*)'", html):
        result = _extract(cfg)
        if result:
            return result

    # Try double-quoted data-config
    for cfg in re.findall(r'data-config="([^"]*)"', html):
        result = _extract(cfg)
        if result:
            return result

    return None


def safe_filename(name: str) -> str:
    s = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return s[:80]


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def _fmt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_size(size_bytes: float) -> str:
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.0f}MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


# ---------------------------------------------------------------------------
# Main download orchestrator
# ---------------------------------------------------------------------------

async def run_download(task: TaskInfo):
    try:
        task.status = "parsing"

        # -- 1. Fetch page HTML ------------------------------------------------
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                task.url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    )
                },
            )
            resp.raise_for_status()
            html = resp.text

        # -- 2. Parse video info -----------------------------------------------
        info = parse_page(html)
        if not info:
            task.status = "failed"
            task.error = "未找到视频地址，请确认页面包含 DPlayer 播放器"
            return

        task.title = info["title"]
        task.filename = safe_filename(info["title"]) + ".mp4"
        filepath = Path(task.download_dir) / task.filename

        # -- 3. Run ffmpeg -----------------------------------------------------
        task.status = "downloading"
        await _run_ffmpeg(info["url"], filepath, task)

        if task.status != "failed":
            task.status = "completed"
            task.progress = 100.0

    except httpx.HTTPStatusError as e:
        task.status = "failed"
        task.error = f"HTTP {e.response.status_code}"
    except httpx.RequestError as e:
        task.status = "failed"
        task.error = f"网络请求失败: {e}"
    except Exception:
        task.status = "failed"
        task.error = f"未知错误"
        raise


# ---------------------------------------------------------------------------
# ffmpeg subprocess with real-time progress parsing
# ---------------------------------------------------------------------------

async def _run_ffmpeg(url: str, filepath: Path, task: TaskInfo):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i", url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        str(filepath),
        "-y",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    duration_secs: float = 0.0
    buf = ""

    while True:
        chunk = await proc.stderr.read(4096)
        if not chunk:
            break
        buf += chunk.decode(errors="replace")

        # Split on \r or \n – ffmpeg uses \r on terminals, \n in pipes
        *lines, buf = re.split(r"[\r\n]+", buf)
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Duration header
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", line)
            if m:
                h, mi, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
                duration_secs = h * 3600 + mi * 60 + s + ms / 100
                task.duration = f"{h:02d}:{mi:02d}:{s:02d}"
                continue

            # Progress line  e.g.  time=00:12:34.56
            m = re.search(r"time=(\d+):(\d+):(\d+)\.(\d+)", line)
            if m and duration_secs > 0:
                h, mi, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
                cur = h * 3600 + mi * 60 + s + ms / 100
                task.current_time = _fmt_time(cur)
                task.progress = min(99.9, (cur / duration_secs) * 100)

            # Speed
            m = re.search(r"speed=\s*(\S+)", line)
            if m:
                task.speed = m.group(1)

            # Output size
            m = re.search(r"size=\s*(\S+)", line)
            if m:
                task.size = m.group(1)

        # Handle cancellation
        if task._cancel:
            proc.terminate()
            task.status = "failed"
            task.error = "用户取消"
            return

    await proc.wait()

    if proc.returncode != 0 and task.status != "failed":
        task.status = "failed"
        task.error = f"ffmpeg 退出码 {proc.returncode}"
