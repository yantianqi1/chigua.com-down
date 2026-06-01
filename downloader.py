"""
Download engine: parses chigua.com pages and downloads videos via ffmpeg.
"""

import asyncio
import json
import logging
import re
import html as html_mod
import traceback
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import httpx

from ffmpeg_runner import build_ffmpeg_args, run_ffmpeg
from settings import ProxySettingsError, normalize_proxy_url

logger = logging.getLogger("downloader")


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
    proxy_url: str = ""
    video_url: str = ""  # pre-resolved m3u8 URL (bypasses page fetch)
    video_title: str = ""  # pre-resolved title
    _cancel: bool = field(default=False, repr=False)


# ---------------------------------------------------------------------------
# Task manager (in-memory)
# ---------------------------------------------------------------------------

class TaskManager:
    def __init__(self):
        self._tasks: dict[str, TaskInfo] = {}

    def create(self, url: str, download_dir: str, proxy_url: str = "", video_url: str = "", video_title: str = "") -> TaskInfo:
        t = TaskInfo(
            id=uuid.uuid4().hex[:8],
            url=url,
            download_dir=download_dir,
            proxy_url=proxy_url,
            video_url=video_url,
            video_title=video_title,
        )
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

def parse_page(html: str) -> list[dict]:
    """Extract all video m3u8 URLs and titles from a chigua.com page."""

    results: list[dict] = []
    page_title = _extract_page_title(html)

    # Collect every <div that carries a data-config attribute, then pull both the
    # video URL and (when present) the data-video_title from the same element.
    for div_match in re.finditer(r"<div\s[^>]*data-config=([^>]*)>", html):
        div_html = div_match.group()

        # --- video URL (single- or double-quoted) --------------------------
        url: str = ""
        for pattern in (r"data-config='([^']*)'", r'data-config="([^"]*)"'):
            cm = re.search(pattern, div_html)
            if cm:
                try:
                    cfg = json.loads(html_mod.unescape(cm.group(1)))
                    url = cfg["video"]["url"]
                except (KeyError, json.JSONDecodeError):
                    pass
                break

        if not url:
            continue

        # --- title ----------------------------------------------------------
        title = ""
        tm = re.search(r'data-video_title="([^"]*)"', div_html)
        if tm:
            title = html_mod.unescape(tm.group(1)).strip()
        if not title:
            title = page_title

        results.append({"url": url, "title": title})

    return results


def _extract_page_title(html: str) -> str:
    """Best-effort page title from <h1> or <title>."""
    hm = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    if hm:
        return re.sub(r"<[^>]+>", "", html_mod.unescape(hm.group(1))).strip()

    ttm = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    if ttm:
        title = re.sub(r"<[^>]+>", "", html_mod.unescape(ttm.group(1))).strip()
        return title.split("|")[0].strip()

    return "video"


def safe_filename(name: str) -> str:
    s = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return s[:80]


# ---------------------------------------------------------------------------
# Main download orchestrator
# ---------------------------------------------------------------------------

async def run_download(task: TaskInfo):
    try:
        task.status = "parsing"

        if task.video_url:
            # Pre-resolved by the endpoint — skip page fetch
            video_url = task.video_url
            title = task.video_title or task.title or "video"
        else:
            # Fallback: fetch page and take the first video
            html = await _fetch_page_html(task.url, task.proxy_url)
            videos = parse_page(html)
            if not videos:
                task.status = "failed"
                task.error = "未找到视频地址，请确认页面包含 DPlayer 播放器"
                return
            video_url = videos[0]["url"]
            title = videos[0]["title"]

        task.title = title
        task.filename = safe_filename(title) + ".mp4"
        filepath = Path(task.download_dir) / task.filename

        task.status = "downloading"
        logger.info("开始下载: %s -> %s", task.filename, filepath)
        await run_ffmpeg(video_url, filepath, task)

        if task.status != "failed":
            task.status = "completed"
            task.progress = 100.0
            logger.info("下载完成: %s", task.filename)

    except ProxySettingsError as e:
        task.status = "failed"
        task.error = f"代理配置错误: {e}"
        logger.error("代理错误 [%s]: %s", task.id, e)
    except httpx.HTTPStatusError as e:
        task.status = "failed"
        task.error = f"HTTP {e.response.status_code}"
        logger.error("HTTP错误 [%s]: %s", task.id, e)
    except httpx.RequestError as e:
        task.status = "failed"
        detail = f"{type(e).__name__}: {e}" if str(e) else repr(e)
        task.error = f"网络请求失败: {detail}"
        logger.error("网络错误 [%s] type=%s: %s", task.id, type(e).__name__, e)
    except Exception as e:
        task.status = "failed"
        task.error = f"{type(e).__name__}: {e}"
        logger.error("下载异常 [%s]: %s\n%s", task.id, e, traceback.format_exc())


async def _fetch_page_html(url: str, proxy_url: str) -> str:
    proxy = normalize_proxy_url(proxy_url) or None
    if proxy:
        logger.info("页面抓取 via 代理 %s: %s", proxy, url)
    else:
        logger.info("页面抓取 直连: %s", url)
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        proxy=proxy,
    ) as client:
        resp = await client.get(url, headers={"User-Agent": _user_agent()})
        resp.raise_for_status()
        return resp.text


def _user_agent() -> str:
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
