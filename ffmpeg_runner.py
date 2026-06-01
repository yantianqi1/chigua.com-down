"""
ffmpeg invocation and progress parsing.
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Protocol

from settings import is_socks_proxy, normalize_proxy_url
from socks_bridge import SocksHttpProxyBridge

logger = logging.getLogger("ffmpeg")


class FfmpegTask(Protocol):
    status: str
    error: str
    duration: str
    current_time: str
    progress: float
    speed: str
    size: str
    proxy_url: str
    _cancel: bool


async def run_ffmpeg(url: str, filepath: Path, task: FfmpegTask):
    proxy_url = normalize_proxy_url(task.proxy_url)
    if is_socks_proxy(proxy_url):
        logger.info("启动 SOCKS5 桥接 -> %s", proxy_url)
        async with SocksHttpProxyBridge(proxy_url) as bridge:
            logger.info("SOCKS5 桥接已启动: %s", bridge.proxy_url)
            await _run_ffmpeg_process(url, filepath, task, bridge.proxy_url)
        return

    await _run_ffmpeg_process(url, filepath, task, proxy_url)


def build_ffmpeg_args(url: str, filepath: Path, proxy_url: str = "") -> list[str]:
    proxy = normalize_proxy_url(proxy_url)
    if is_socks_proxy(proxy):
        raise ValueError("SOCKS5 代理必须先转换为本地 HTTP 代理")

    args = ["ffmpeg"]
    if proxy:
        args.extend(("-http_proxy", proxy))
    args.extend(_ffmpeg_output_args(url, filepath))
    return args


def _ffmpeg_output_args(url: str, filepath: Path) -> tuple[str, ...]:
    return ("-i", url, "-c", "copy", "-bsf:a", "aac_adtstoasc", str(filepath), "-y")


async def _run_ffmpeg_process(
    url: str,
    filepath: Path,
    task: FfmpegTask,
    proxy_url: str,
):
    args = build_ffmpeg_args(url, filepath, proxy_url)
    logger.info("ffmpeg 进程启动: %s", " ".join(args))
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await _read_ffmpeg_progress(proc, task)
    await proc.wait()

    if proc.returncode != 0 and task.status != "failed":
        task.status = "failed"
        task.error = f"ffmpeg 退出码 {proc.returncode}"
        logger.error("ffmpeg 退出码 %d: %s", proc.returncode, task.error)


async def _read_ffmpeg_progress(proc: asyncio.subprocess.Process, task: FfmpegTask):
    duration_secs: float = 0.0
    buf = ""

    while True:
        chunk = await proc.stderr.read(4096)
        if not chunk:
            break
        buf += chunk.decode(errors="replace")

        *lines, buf = re.split(r"[\r\n]+", buf)
        for line in lines:
            duration_secs = _handle_ffmpeg_line(line.strip(), duration_secs, task)

        if task._cancel:
            proc.terminate()
            task.status = "failed"
            task.error = "用户取消"
            return


def _handle_ffmpeg_line(line: str, duration_secs: float, task: FfmpegTask) -> float:
    if not line:
        return duration_secs

    duration = _read_duration(line, task)
    if duration is not None:
        return duration

    _read_progress(line, duration_secs, task)
    _read_speed(line, task)
    _read_output_size(line, task)
    return duration_secs


def _read_duration(line: str, task: FfmpegTask) -> float | None:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", line)
    if not match:
        return None

    seconds = _match_seconds(match)
    task.duration = f"{int(match[1]):02d}:{int(match[2]):02d}:{int(match[3]):02d}"
    return seconds


def _read_progress(line: str, duration_secs: float, task: FfmpegTask):
    match = re.search(r"time=(\d+):(\d+):(\d+)\.(\d+)", line)
    if not match or duration_secs <= 0:
        return

    current = _match_seconds(match)
    task.current_time = _fmt_time(current)
    task.progress = min(99.9, (current / duration_secs) * 100)


def _read_speed(line: str, task: FfmpegTask):
    match = re.search(r"speed=\s*(\S+)", line)
    if match:
        task.speed = match.group(1)


def _read_output_size(line: str, task: FfmpegTask):
    match = re.search(r"size=\s*(\S+)", line)
    if match:
        task.size = match.group(1)


def _match_seconds(match: re.Match) -> float:
    hours, minutes, seconds = int(match[1]), int(match[2]), int(match[3])
    return hours * 3600 + minutes * 60 + seconds + float(f"0.{match[4]}")


def _fmt_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{remaining:02d}"
