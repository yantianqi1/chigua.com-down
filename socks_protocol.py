"""
SOCKS5 client protocol helpers for the local proxy bridge.
"""

import asyncio
import ipaddress
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

SOCKS_VERSION = 5
SOCKS_CONNECT = 1
SOCKS_AUTH_NONE = 0
SOCKS_AUTH_PASSWORD = 2


class SocksBridgeError(RuntimeError):
    """Raised when SOCKS5 proxy negotiation or HTTP proxying fails."""


@dataclass(frozen=True)
class SocksProxy:
    host: str
    port: int
    username: str = ""
    password: str = ""


def parse_socks_proxy(proxy_url: str) -> SocksProxy:
    parts = urlsplit(proxy_url.strip())
    if parts.scheme not in ("socks5", "socks5h"):
        raise ValueError("SOCKS 桥接只支持 socks5 或 socks5h")

    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("SOCKS5 代理端口无效") from exc

    if not parts.hostname or port is None:
        raise ValueError("SOCKS5 代理必须包含服务器和端口")

    username = unquote(parts.username or "")
    password = unquote(parts.password or "")
    _validate_auth_field(username, "用户名")
    _validate_auth_field(password, "密码")
    return SocksProxy(parts.hostname, port, username, password)


async def open_socks_connection(
    proxy: SocksProxy,
    target_host: str,
    target_port: int,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection(proxy.host, proxy.port)
    try:
        await _socks_greeting(proxy, reader, writer)
        await _socks_connect(target_host, target_port, reader, writer)
        return reader, writer
    except Exception:
        await close_writer(writer)
        raise


async def close_writer(writer: asyncio.StreamWriter):
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


def _validate_auth_field(value: str, label: str):
    if len(value.encode("utf-8")) > 255:
        raise ValueError(f"SOCKS5 {label}长度不能超过 255 字节")


async def _socks_greeting(
    proxy: SocksProxy,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
):
    methods = bytes([SOCKS_AUTH_PASSWORD if proxy.username or proxy.password else 0])
    writer.write(bytes([SOCKS_VERSION, len(methods)]) + methods)
    await writer.drain()

    version, method = await reader.readexactly(2)
    if version != SOCKS_VERSION or method == 0xFF:
        raise SocksBridgeError("SOCKS5 代理不接受认证方式")
    if method == SOCKS_AUTH_PASSWORD:
        await _socks_password_auth(proxy, reader, writer)
    elif method != SOCKS_AUTH_NONE:
        raise SocksBridgeError("SOCKS5 代理返回了不支持的认证方式")


async def _socks_password_auth(
    proxy: SocksProxy,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
):
    username = proxy.username.encode("utf-8")
    password = proxy.password.encode("utf-8")
    payload = b"\x01" + bytes([len(username)]) + username
    writer.write(payload + bytes([len(password)]) + password)
    await writer.drain()

    version, status = await reader.readexactly(2)
    if version != 1 or status != 0:
        raise SocksBridgeError("SOCKS5 用户名或密码认证失败")


async def _socks_connect(
    host: str,
    port: int,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
):
    writer.write(bytes([SOCKS_VERSION, SOCKS_CONNECT, 0]))
    writer.write(_encode_socks_address(host, port))
    await writer.drain()

    version, reply, _, address_type = await reader.readexactly(4)
    if version != SOCKS_VERSION or reply != 0:
        raise SocksBridgeError(f"SOCKS5 连接目标失败，响应码 {reply}")
    await _read_socks_bind_address(reader, address_type)
    await reader.readexactly(2)


def _encode_socks_address(host: str, port: int) -> bytes:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        host_bytes = host.encode("idna")
        return bytes([3, len(host_bytes)]) + host_bytes + port.to_bytes(2, "big")

    address_type = 1 if ip.version == 4 else 4
    return bytes([address_type]) + ip.packed + port.to_bytes(2, "big")


async def _read_socks_bind_address(reader: asyncio.StreamReader, address_type: int):
    if address_type == 1:
        await reader.readexactly(4)
    elif address_type == 3:
        length = (await reader.readexactly(1))[0]
        await reader.readexactly(length)
    elif address_type == 4:
        await reader.readexactly(16)
    else:
        raise SocksBridgeError("SOCKS5 代理返回了未知地址类型")
