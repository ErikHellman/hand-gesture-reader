"""Control channel for `handsign ctl`: one JSON line per request / response.

A unix socket in $XDG_RUNTIME_DIR where available, otherwise TCP on localhost.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

COMMANDS = ("status", "pause", "resume", "toggle", "quit")
_TCP_ADDRESS = ("127.0.0.1", 47813)
_HAS_UNIX = hasattr(socket, "AF_UNIX") and os.name != "nt"


def socket_path() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / "handsign.sock"


def _listen() -> socket.socket:
    if _HAS_UNIX:
        path = socket_path()
        if path.exists():
            # Stale socket from a crashed daemon, or another instance?
            try:
                send("status", timeout=0.5)
            except OSError:
                path.unlink()
            else:
                raise RuntimeError("handsign is already running")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        os.chmod(path, 0o600)
    else:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(_TCP_ADDRESS)
    server.listen(4)
    return server


class ControlServer:
    """Calls handler(command) -> dict on a background thread for every request."""

    def __init__(self, handler: Callable[[str], dict]) -> None:
        self._handler = handler
        self._server = _listen()
        self._thread = threading.Thread(target=self._serve, name="control", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return  # closed
            with conn:
                try:
                    conn.settimeout(2.0)
                    command = conn.makefile("r", encoding="utf-8").readline().strip()
                    if command in COMMANDS:
                        reply = self._handler(command)
                    else:
                        reply = {"ok": False, "error": f"unknown command {command!r}"}
                    conn.sendall((json.dumps(reply) + "\n").encode())
                except Exception as err:  # never let a bad client kill the thread
                    log.debug("control connection failed: %s", err)

    def close(self) -> None:
        self._server.close()
        if _HAS_UNIX:
            socket_path().unlink(missing_ok=True)


def send(command: str, timeout: float = 3.0) -> dict:
    """Client side. Raises OSError if the daemon is not reachable."""
    if _HAS_UNIX:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        address: str | tuple[str, int] = str(socket_path())
    else:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        address = _TCP_ADDRESS
    with client:
        client.settimeout(timeout)
        client.connect(address)
        client.sendall((command + "\n").encode())
        line = client.makefile("r", encoding="utf-8").readline()
    return json.loads(line) if line else {"ok": False, "error": "empty reply"}
