"""Synthetic key presses.

Linux: a virtual keyboard through /dev/uinput (python-evdev). Works on Wayland, X11 and the
console because the events enter at kernel level. Note that uinput sends key *codes*: letters
follow the active keyboard layout.
macOS / Windows: pynput. On macOS the responsible app needs Accessibility access.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Any, Protocol

from .base import ActionError, check_keys, register

log = logging.getLogger(__name__)

# Friendly name -> Linux KEY_* suffix. Anything else is looked up as KEY_<NAME>.
_EVDEV_ALIASES = {
    "ctrl": "LEFTCTRL", "control": "LEFTCTRL", "shift": "LEFTSHIFT", "alt": "LEFTALT",
    "altgr": "RIGHTALT", "super": "LEFTMETA", "meta": "LEFTMETA", "win": "LEFTMETA",
    "cmd": "LEFTMETA", "return": "ENTER", "escape": "ESC", "del": "DELETE", "ins": "INSERT",
    "pgup": "PAGEUP", "pgdn": "PAGEDOWN", "pagedown": "PAGEDOWN", "pageup": "PAGEUP",
    "plus": "KPPLUS", "minus": "MINUS", "period": "DOT", "volup": "VOLUMEUP",
    "voldown": "VOLUMEDOWN", "next": "NEXTSONG", "prev": "PREVIOUSSONG", "previous": "PREVIOUSSONG",
    "play": "PLAYPAUSE", "brightnessup": "BRIGHTNESSUP", "brightnessdown": "BRIGHTNESSDOWN",
}  # fmt: skip

_PYNPUT_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt", "altgr": "alt_gr",
    "super": "cmd", "meta": "cmd", "win": "cmd", "cmd": "cmd", "return": "enter",
    "enter": "enter", "escape": "esc", "esc": "esc", "del": "delete", "ins": "insert",
    "pgup": "page_up", "pageup": "page_up", "pgdn": "page_down", "pagedown": "page_down",
    "volup": "media_volume_up", "volumeup": "media_volume_up", "voldown": "media_volume_down",
    "volumedown": "media_volume_down", "mute": "media_volume_mute", "next": "media_next",
    "nextsong": "media_next", "prev": "media_previous", "previous": "media_previous",
    "previoussong": "media_previous", "play": "media_play_pause", "playpause": "media_play_pause",
}  # fmt: skip


def parse_combo(combo: str) -> list[str]:
    """Split "ctrl+alt+Right" into ["ctrl", "alt", "right"]: pressed in order, released reversed."""
    if not isinstance(combo, str):
        raise ActionError(f"key combo must be a string, got {combo!r}")
    keys = [k.strip().lower() for k in combo.split("+")]
    if not keys or any(not k for k in keys):
        raise ActionError(f"invalid key combo {combo!r}")
    return keys


class KeyBackend(Protocol):
    def validate(self, keys: list[str]) -> None: ...

    def tap(self, keys: list[str]) -> None: ...


class EvdevBackend:
    def __init__(self) -> None:
        from evdev import ecodes

        self._ecodes = ecodes
        self._device = None
        self._lock = threading.Lock()

    def _code(self, key: str) -> int:
        name = "KEY_" + _EVDEV_ALIASES.get(key, key.upper())
        code = self._ecodes.ecodes.get(name)
        if code is None:
            raise ActionError(f"unknown key {key!r} (no {name} in linux/input-event-codes.h)")
        return code

    def validate(self, keys: list[str]) -> None:
        for key in keys:
            self._code(key)

    def open(self) -> None:
        """Create the virtual keyboard. Done at startup: compositors need a moment to pick
        up a new input device, and events sent before that are lost."""
        from evdev import UInput

        with self._lock:
            if self._device is not None:
                return
            e = self._ecodes
            all_keys = [c for n, c in e.ecodes.items() if n.startswith("KEY_") and c < 0x2FF]
            try:
                self._device = UInput({e.EV_KEY: sorted(set(all_keys))}, name="handsign-keyboard")
            except OSError as err:
                raise ActionError(
                    f"cannot open /dev/uinput ({err}). Grant access with a udev rule — see README."
                ) from err
        time.sleep(0.5)

    def tap(self, keys: list[str]) -> None:
        self.open()
        codes = [self._code(k) for k in keys]
        e = self._ecodes
        with self._lock:
            for code in codes:
                self._device.write(e.EV_KEY, code, 1)
                self._device.syn()
            time.sleep(0.01)
            for code in reversed(codes):
                self._device.write(e.EV_KEY, code, 0)
                self._device.syn()

    def close(self) -> None:
        with self._lock:
            if self._device is not None:
                self._device.close()
                self._device = None


class PynputBackend:
    def __init__(self) -> None:
        try:
            from pynput import keyboard
        except ImportError as err:
            raise ActionError(
                "keys actions need pynput on this platform: pip install pynput"
            ) from err
        self._keyboard = keyboard
        self._controller = keyboard.Controller()

    def _key(self, key: str):
        name = _PYNPUT_ALIASES.get(key, key)
        if hasattr(self._keyboard.Key, name):
            return getattr(self._keyboard.Key, name)
        if len(key) == 1:
            return key
        raise ActionError(f"unknown key {key!r}")

    def validate(self, keys: list[str]) -> None:
        for key in keys:
            self._key(key)

    def open(self) -> None:
        if sys.platform == "darwin":
            _check_accessibility()

    def tap(self, keys: list[str]) -> None:
        resolved = [self._key(k) for k in keys]
        for key in resolved:
            self._controller.press(key)
        for key in reversed(resolved):
            self._controller.release(key)

    def close(self) -> None:
        pass


def _check_accessibility() -> None:
    """macOS drops synthetic key events silently without Accessibility access. Asking also
    makes the system show its prompt for the responsible app (Handsign.app or the terminal)."""
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        trusted = AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    except Exception as err:  # pyobjc comes with pynput, but never fail startup over this
        log.debug("cannot check Accessibility access: %s", err)
        return
    if not trusted:
        log.warning(
            "keys actions need Accessibility access: System Settings → Privacy & Security → "
            "Accessibility → enable Handsign (the service) or your terminal app"
        )


_backend: KeyBackend | None = None


def get_backend() -> KeyBackend:
    global _backend
    if _backend is None:
        _backend = EvdevBackend() if sys.platform.startswith("linux") else PynputBackend()
    return _backend


def set_backend(backend: KeyBackend | None) -> None:
    """Override the backend (tests)."""
    global _backend
    _backend = backend


class KeysAction:
    def __init__(self, combos: list[list[str]], delay_ms: float = 30.0) -> None:
        self.combos = combos
        self.delay = delay_ms / 1000.0
        get_backend().validate([k for combo in combos for k in combo])

    def run(self) -> None:
        backend = get_backend()
        for i, combo in enumerate(self.combos):
            if i:
                time.sleep(self.delay)
            backend.tap(combo)

    def describe(self) -> str:
        return "keys " + ", ".join("+".join(c) for c in self.combos)


@register("keys")
def _build(spec: dict[str, Any]) -> KeysAction:
    check_keys(spec, {"combo", "sequence", "delay_ms"}, "keys")
    if ("combo" in spec) == ("sequence" in spec):
        raise ActionError("keys action needs exactly one of 'combo' or 'sequence'")
    raw = [spec["combo"]] if "combo" in spec else spec["sequence"]
    if not isinstance(raw, list) or not raw:
        raise ActionError("keys action: 'sequence' must be a non-empty list of combos")
    return KeysAction([parse_combo(c) for c in raw], float(spec.get("delay_ms", 30.0)))
