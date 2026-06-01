import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main
from settings import SettingsStore


class ApiSettingsTest(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._old_store = main.settings_store
        settings_path = Path(self._tmp_dir.name) / "settings.json"
        main.settings_store = SettingsStore(settings_path)
        self.client = TestClient(main.app)

    def tearDown(self):
        main.settings_store = self._old_store
        self._tmp_dir.cleanup()

    def test_proxy_settings_round_trip(self):
        proxy_url = "socks5://user:pass@10.0.0.2:1080"

        post_resp = self.client.post(
            "/api/settings/proxy",
            json={"proxy_url": proxy_url},
        )
        get_resp = self.client.get("/api/settings/proxy")

        self.assertEqual(post_resp.status_code, 200)
        self.assertEqual(post_resp.json(), {"proxy_url": proxy_url})
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json(), {"proxy_url": proxy_url})

    def test_proxy_settings_rejects_invalid_url(self):
        response = self.client.post(
            "/api/settings/proxy",
            json={"proxy_url": "ftp://10.0.0.2:21"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("代理协议", response.json()["detail"])

    def test_create_tasks_one_per_video(self):
        videos = (
            '<div class="dplayer" data-video_title="P1"'
            " data-config='{\"video\":{\"url\":\"https://cdn.example.com/1.m3u8\"}}'></div>"
            '<div class="dplayer" data-video_title="P2"'
            " data-config='{\"video\":{\"url\":\"https://cdn.example.com/2.m3u8\"}}'></div>"
        )
        with patch("main._fetch_page_html", return_value=videos), patch(
            "main.run_download", new_callable=AsyncMock
        ):
            response = self.client.post(
                "/api/tasks",
                json={"urls": "https://chigua.com/archives/test/", "download_dir": "/tmp"},
            )

        self.assertEqual(response.status_code, 200)
        tasks = response.json()
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["title"], "P1")
        self.assertEqual(tasks[1]["title"], "P2")


if __name__ == "__main__":
    unittest.main()
