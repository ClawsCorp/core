from __future__ import annotations

import asyncio
import os
import socket
from typing import Any

import uvicorn

from .main import app


def _try_set(sock: socket.socket, level: int, opt: int, value: int) -> None:
    try:
        sock.setsockopt(level, opt, value)
    except OSError:
        # Best-effort: not all platforms/containers allow changing all options.
        pass


def _listen_ipv6(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    _try_set(s, socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Bind IPv6-only so we can also bind IPv4 on the same port without EADDRINUSE.
    # This avoids platform-specific dual-stack quirks that can break edge connectivity.
    _try_set(s, socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    s.bind(("::", port))
    s.listen(2048)
    s.setblocking(False)
    return s


def _listen_ipv4(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _try_set(s, socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(2048)
    s.setblocking(False)
    return s


def _build_sockets(port: int) -> list[socket.socket]:
    sockets: list[socket.socket] = []

    # Bind IPv4 first (most PaaS proxies still default to IPv4 internally).
    try:
        sockets.append(_listen_ipv4(port))
        print(f"[server] listening on 0.0.0.0:{port}", flush=True)
    except OSError as exc:
        print(f"[server] failed to bind IPv4 0.0.0.0:{port}: {exc!r}", flush=True)

    # Then bind IPv6 (v6-only so it won't conflict with the IPv4 socket).
    try:
        sockets.append(_listen_ipv6(port))
        print(f"[server] listening on [::]:{port}", flush=True)
    except OSError as exc:
        print(f"[server] failed to bind IPv6 [::]:{port}: {exc!r}", flush=True)

    if not sockets:
        raise RuntimeError(f"Failed to bind any listener sockets on port {port}")

    return sockets


def main() -> None:
    port = int(os.getenv("PORT", "8000"))

    # proxy_headers=True: trust X-Forwarded-* from Railway edge/proxy
    config = uvicorn.Config(
        app,
        host=None,  # we're providing pre-bound sockets
        port=None,
        proxy_headers=True,
        log_level="info",
        access_log=True,
    )
    server: Any = uvicorn.Server(config)
    sockets = _build_sockets(port)

    asyncio.run(server.serve(sockets=sockets))


if __name__ == "__main__":
    main()
