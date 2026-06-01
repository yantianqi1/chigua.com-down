"""
Local HTTP CONNECT proxy that forwards traffic through an upstream SOCKS5 proxy.
"""

import asyncio
import contextlib
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from socks_protocol import (
    SocksBridgeError,
    SocksProxy,
    close_writer,
    open_socks_connection,
    parse_socks_proxy,
)

BUFFER_SIZE = 65536
MAX_HEADER_BYTES = 65536
HTTP_CONNECT_OK = b"HTTP/1.1 200 Connection Established\r\n\r\n"


class SocksHttpProxyBridge:
    def __init__(self, upstream_proxy_url: str):
        self._upstream = parse_socks_proxy(upstream_proxy_url)
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task] = set()

    @property
    def proxy_url(self) -> str:
        if not self._server or not self._server.sockets:
            raise RuntimeError("SOCKS 桥接服务尚未启动")

        port = self._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def __aenter__(self) -> "SocksHttpProxyBridge":
        self._server = await asyncio.start_server(
            self._handle_client,
            "127.0.0.1",
            0,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _handle_client(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ):
        task = asyncio.current_task()
        if task:
            self._tasks.add(task)

        try:
            await self._proxy_client(client_reader, client_writer)
        finally:
            if task:
                self._tasks.discard(task)
            await close_writer(client_writer)

    async def _proxy_client(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ):
        request = await _read_http_request(client_reader)
        remote_reader, remote_writer = await open_socks_connection(
            self._upstream,
            request.host,
            request.port,
        )

        try:
            if request.method == "CONNECT":
                client_writer.write(HTTP_CONNECT_OK)
                await client_writer.drain()
            initial_bytes = _initial_remote_bytes(request)
            if initial_bytes:
                remote_writer.write(initial_bytes)
                await remote_writer.drain()
            await _relay(client_reader, client_writer, remote_reader, remote_writer)
        finally:
            await close_writer(remote_writer)


@dataclass(frozen=True)
class HttpProxyRequest:
    method: str
    host: str
    port: int
    forward_bytes: bytes


def _initial_remote_bytes(request: HttpProxyRequest) -> bytes:
    return request.forward_bytes


async def _read_http_request(reader: asyncio.StreamReader) -> HttpProxyRequest:
    header, body = await _read_header(reader)
    lines = header.split("\r\n")
    method, target, version = _parse_request_line(lines[0])
    headers = tuple(lines[1:])

    if method == "CONNECT":
        host, port = _parse_authority(target, 443)
        return HttpProxyRequest(method, host, port, body)

    return _build_forward_request(method, target, version, headers, body)


async def _read_header(reader: asyncio.StreamReader) -> tuple[str, bytes]:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = await reader.read(4096)
        if not chunk:
            raise SocksBridgeError("客户端未发送完整 HTTP 代理请求")
        data.extend(chunk)
        if len(data) > MAX_HEADER_BYTES:
            raise SocksBridgeError("HTTP 代理请求头过大")

    header, body = bytes(data).split(b"\r\n\r\n", 1)
    return header.decode("iso-8859-1"), body


def _parse_request_line(line: str) -> tuple[str, str, str]:
    parts = line.split(" ", 2)
    if len(parts) != 3:
        raise SocksBridgeError("HTTP 代理请求行无效")
    return parts[0].upper(), parts[1], parts[2]


def _build_forward_request(
    method: str,
    target: str,
    version: str,
    headers: tuple[str, ...],
    body: bytes,
) -> HttpProxyRequest:
    parts = urlsplit(target)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SocksBridgeError("HTTP 代理请求目标无效")

    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
    header_lines = [f"{method} {path} {version}", *_filter_proxy_headers(headers)]
    forward_bytes = ("\r\n".join(header_lines) + "\r\n\r\n").encode("iso-8859-1")
    return HttpProxyRequest(method, parts.hostname, port, forward_bytes + body)


def _filter_proxy_headers(headers: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(h for h in headers if not h.lower().startswith("proxy-connection:"))


def _parse_authority(authority: str, default_port: int) -> tuple[str, int]:
    parts = urlsplit(f"//{authority}")
    if not parts.hostname:
        raise SocksBridgeError("CONNECT 目标地址无效")
    return parts.hostname, parts.port or default_port


async def _relay(*streams):
    left_reader, left_writer, right_reader, right_writer = streams
    left = asyncio.create_task(_pipe(left_reader, right_writer))
    right = asyncio.create_task(_pipe(right_reader, left_writer))
    done, pending = await asyncio.wait((left, right), return_when=asyncio.FIRST_COMPLETED)

    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        task.result()


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    while True:
        chunk = await reader.read(BUFFER_SIZE)
        if not chunk:
            break
        writer.write(chunk)
        await writer.drain()

    with contextlib.suppress(Exception):
        writer.write_eof()
