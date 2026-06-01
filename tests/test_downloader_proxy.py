import asyncio
import tempfile
import unittest
from pathlib import Path

from downloader import TaskManager, build_ffmpeg_args, parse_page
from socks_bridge import (
    HttpProxyRequest,
    SocksHttpProxyBridge,
    _initial_remote_bytes,
    parse_socks_proxy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dplayer_div(title: str, video_url: str) -> str:
    """Build a realistic DPlayer div snippet."""
    config = (
        '{"live":false,"autoplay":false,"video":{"url":"'
        + video_url
        + '","type":"hls"}}'
    )
    return f'<div class="dplayer" data-video_title="{title}" data-config=\'{config}\'></div>'


MULTI_VIDEO_HTML = (
    "<html><head><title>Page Title | Site</title></head><body>"
    + _dplayer_div("视频一", "https://cdn.example.com/video1.m3u8")
    + _dplayer_div("视频二", "https://cdn.example.com/video2.m3u8")
    + _dplayer_div("视频三", "https://cdn.example.com/video3.m3u8")
    + "</body></html>"
)

SINGLE_VIDEO_HTML = (
    "<html><head><title>Single</title></head><body>"
    + _dplayer_div("唯一视频", "https://cdn.example.com/single.m3u8")
    + "</body></html>"
)

NO_VIDEO_HTML = "<html><body><p>No DPlayer here</p></body></html>"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class DownloaderProxyTest(unittest.TestCase):
    def test_task_manager_snapshots_proxy_url(self):
        manager = TaskManager()

        task = manager.create(
            "https://chigua.com/archives/259956/",
            "/downloads",
            "http://user:pass@10.0.0.2:8080",
        )

        self.assertEqual(task.proxy_url, "http://user:pass@10.0.0.2:8080")

    def test_build_ffmpeg_args_adds_http_proxy(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "video.mp4"

            args = build_ffmpeg_args(
                "https://cdn.example.com/video.m3u8",
                output_path,
                "http://user:pass@10.0.0.2:8080",
            )

        self.assertEqual(args[0], "ffmpeg")
        self.assertIn("-http_proxy", args)
        self.assertIn("http://user:pass@10.0.0.2:8080", args)
        self.assertEqual(args[-2:], [str(output_path), "-y"])

    def test_build_ffmpeg_args_rejects_socks_proxy_directly(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "video.mp4"

            with self.assertRaises(ValueError):
                build_ffmpeg_args(
                    "https://cdn.example.com/video.m3u8",
                    output_path,
                    "socks5://user:pass@10.0.0.2:1080",
                )

    def test_parse_socks_proxy_with_auth(self):
        proxy = parse_socks_proxy("socks5://user:pass@10.0.0.2:1080")

        self.assertEqual(proxy.host, "10.0.0.2")
        self.assertEqual(proxy.port, 1080)
        self.assertEqual(proxy.username, "user")
        self.assertEqual(proxy.password, "pass")

    def test_socks_bridge_exposes_local_http_proxy_url(self):
        async def run_bridge():
            async with SocksHttpProxyBridge(
                "socks5://user:pass@127.0.0.1:1080"
            ) as bridge:
                self.assertRegex(bridge.proxy_url, r"^http://127\.0\.0\.1:\d+$")

        asyncio.run(run_bridge())

    def test_connect_request_preserves_initial_bytes(self):
        request = HttpProxyRequest("CONNECT", "example.com", 443, b"tls-client-hello")

        self.assertEqual(_initial_remote_bytes(request), b"tls-client-hello")


class ParsePageTest(unittest.TestCase):
    def test_parses_multiple_videos(self):
        videos = parse_page(MULTI_VIDEO_HTML)

        self.assertEqual(len(videos), 3)
        self.assertEqual(videos[0]["title"], "视频一")
        self.assertEqual(videos[0]["url"], "https://cdn.example.com/video1.m3u8")
        self.assertEqual(videos[1]["title"], "视频二")
        self.assertEqual(videos[2]["title"], "视频三")

    def test_parses_single_video(self):
        videos = parse_page(SINGLE_VIDEO_HTML)

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["title"], "唯一视频")
        self.assertEqual(videos[0]["url"], "https://cdn.example.com/single.m3u8")

    def test_returns_empty_list_when_no_dplayer(self):
        videos = parse_page(NO_VIDEO_HTML)
        self.assertEqual(videos, [])

    def test_falls_back_to_h1_title(self):
        html = (
            "<html><body><h1>文章标题</h1>"
            + '<div class="dplayer" data-config=\'{"video":{"url":"https://cdn.example.com/v.m3u8"}}\'></div>'
            + "</body></html>"
        )
        videos = parse_page(html)

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["title"], "文章标题")
        self.assertEqual(videos[0]["url"], "https://cdn.example.com/v.m3u8")


if __name__ == "__main__":
    unittest.main()
