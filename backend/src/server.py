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
    # Prefer dual-stack if possible (so one listener can accept both v4+v6).
    # If the platform forces v6-only, we'll add an IPv4 listener below.
    _try_set(s, socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
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

    # Create IPv6 first; if it ends up dual-stack, IPv4 bind may fail and we can ignore it.
    try:
        sockets.append(_listen_ipv6(port))
        print(f"[server] listening on [::]:{port}", flush=True)
    except OSError as exc:
        print(f"[server] failed to bind IPv6 [::]:{port}: {exc!r}", flush=True)

    try:
        sockets.append(_listen_ipv4(port))
        print(f"[server] listening on 0.0.0.0:{port}", flush=True)
    except OSError as exc:
        # If IPv6 listener is dual-stack, this can be a harmless EADDRINUSE.
        if sockets:
            print(f"[server] IPv4 bind skipped (likely dual-stack): {exc!r}", flush=True)
        else:
            raise

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

