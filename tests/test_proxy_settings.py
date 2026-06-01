import json
import tempfile
import unittest
from pathlib import Path

from settings import ProxySettingsError, SettingsStore, normalize_proxy_url


class ProxySettingsTest(unittest.TestCase):
    def test_normalizes_supported_proxy_urls(self):
        cases = (
            "http://user:pass@10.0.0.2:8080",
            "https://user:pass@10.0.0.2:8443",
            "socks5://user:pass@10.0.0.2:1080",
            "socks5h://user:pass@10.0.0.2:1080",
        )

        for proxy_url in cases:
            with self.subTest(proxy_url=proxy_url):
                self.assertEqual(normalize_proxy_url(f" {proxy_url} "), proxy_url)

    def test_rejects_invalid_proxy_scheme(self):
        with self.assertRaises(ProxySettingsError):
            normalize_proxy_url("ftp://user:pass@10.0.0.2:21")

    def test_rejects_proxy_without_host_or_port(self):
        invalid_urls = (
            "http://user:pass@:8080",
            "http://user:pass@10.0.0.2",
            "socks5://user:pass@10.0.0.2:not-a-port",
        )

        for proxy_url in invalid_urls:
            with self.subTest(proxy_url=proxy_url):
                with self.assertRaises(ProxySettingsError):
                    normalize_proxy_url(proxy_url)

    def test_empty_proxy_clears_setting(self):
        self.assertEqual(normalize_proxy_url("  "), "")

    def test_settings_store_persists_proxy_url(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "settings.json"
            store = SettingsStore(settings_path)

            saved = store.save_proxy(" http://user:pass@10.0.0.2:8080 ")

            self.assertEqual(saved.proxy_url, "http://user:pass@10.0.0.2:8080")
            self.assertEqual(store.load().proxy_url, saved.proxy_url)
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, {"proxy_url": saved.proxy_url})


if __name__ == "__main__":
    unittest.main()
