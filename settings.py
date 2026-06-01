"""
Persistent application settings.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


SUPPORTED_PROXY_SCHEMES = frozenset(("http", "https", "socks5", "socks5h"))
DEFAULT_SETTINGS_PATH = Path(os.getenv("CHIGUA_SETTINGS_PATH", "/downloads/settings.json"))


class ProxySettingsError(ValueError):
    """Raised when the configured proxy URL is invalid."""


@dataclass(frozen=True)
class AppSettings:
    proxy_url: str = ""


def normalize_proxy_url(proxy_url: str) -> str:
    value = proxy_url.strip()
    if not value:
        return ""

    parts = urlsplit(value)
    if parts.scheme not in SUPPORTED_PROXY_SCHEMES:
        raise ProxySettingsError("代理协议只支持 http、https、socks5、socks5h")

    try:
        port = parts.port
    except ValueError as exc:
        raise ProxySettingsError("代理端口无效") from exc

    if not parts.hostname or port is None:
        raise ProxySettingsError("代理地址必须包含服务器和端口")

    return value


def is_socks_proxy(proxy_url: str) -> bool:
    if not proxy_url.strip():
        return False

    return urlsplit(normalize_proxy_url(proxy_url)).scheme in ("socks5", "socks5h")


class SettingsStore:
    def __init__(self, path: Path = DEFAULT_SETTINGS_PATH):
        self._path = path

    def load(self) -> AppSettings:
        if not self._path.exists():
            return AppSettings()

        data = json.loads(self._path.read_text(encoding="utf-8"))
        proxy_url = normalize_proxy_url(str(data.get("proxy_url", "")))
        return AppSettings(proxy_url=proxy_url)

    def save_proxy(self, proxy_url: str) -> AppSettings:
        settings = AppSettings(proxy_url=normalize_proxy_url(proxy_url))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"proxy_url": settings.proxy_url}, ensure_ascii=False)
        self._path.write_text(payload, encoding="utf-8")
        return settings
