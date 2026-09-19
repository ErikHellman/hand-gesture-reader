"""Hyprland dispatchers via hyprctl."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .base import ActionError, check_keys, register
from .command import CommandAction


def _instance_signature() -> str | None:
    """Find the running Hyprland instance when the env var is missing (e.g. under systemd)."""
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig:
        return sig
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        return None
    sockets = sorted(
        Path(runtime, "hypr").glob("*/.socket.sock"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return sockets[0].parent.name if sockets else None


class HyprlandAction(CommandAction):
    """`dispatch` is handed to `hyprctl dispatch`.

    Lua-configured Hyprland (0.55+) expects a dispatcher expression such as
    `hl.dsp.focus({ workspace = "e+1" })`; older versions take `workspace e+1`.
    """

    def __init__(self, dispatch: str) -> None:
        args = [dispatch] if dispatch.startswith("hl.") else dispatch.split(None, 1)
        super().__init__(["hyprctl", "dispatch", *args])

    def run(self) -> None:
        sig = _instance_signature()
        self.env = {**os.environ, "HYPRLAND_INSTANCE_SIGNATURE": sig} if sig else None
        super().run()


@register("hyprland")
def _build(spec: dict[str, Any]) -> HyprlandAction:
    check_keys(spec, {"dispatch"}, "hyprland")
    dispatch = spec.get("dispatch")
    if not isinstance(dispatch, str) or not dispatch.strip():
        raise ActionError(
            "hyprland action needs 'dispatch', e.g. 'hl.dsp.focus({ workspace = \"e+1\" })'"
        )
    if shutil.which("hyprctl") is None:
        raise ActionError("hyprland action is unsupported here: hyprctl not found")
    return HyprlandAction(dispatch.strip())
