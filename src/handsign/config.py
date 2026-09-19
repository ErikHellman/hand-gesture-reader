"""TOML configuration -> dataclasses, with validation."""

from __future__ import annotations

import dataclasses
import os
import sys
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from .actions import Action, ActionError, build_action
from .motion import MotionConfig
from .poses import POSES, PoseThresholds

SWIPES = ("swipe_left", "swipe_right", "swipe_up", "swipe_down")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class CameraConfig:
    device: int | str = 0
    width: int = 640
    height: int = 480
    fps: int = 30
    mirror: bool = True


@dataclass(frozen=True)
class RecognitionConfig:
    max_hands: int = 1
    min_confidence: float = 0.6
    hold_ms: float = 400.0
    vote_window_ms: float = 300.0
    vote_ratio: float = 0.7
    # Hand speed (hand sizes / second) above which static poses are ignored.
    max_pose_speed: float = 2.5
    thresholds: PoseThresholds = PoseThresholds()


@dataclass(frozen=True)
class ArmingConfig:
    enabled: bool = True
    pose: str = "open_palm"
    hold_ms: float = 600.0
    timeout_s: float = 5.0
    disarm_pose: str = "fist"


@dataclass(frozen=True)
class IdleConfig:
    after_s: float = 5.0
    fps: float = 5.0


@dataclass(frozen=True)
class FeedbackConfig:
    notify: bool = True  # desktop notification on arm / disarm
    notify_gestures: bool = False  # ... and on every dispatched gesture


@dataclass(frozen=True)
class Binding:
    gesture: str
    action: Action
    hand: str | None = None  # "left" / "right" / None = either
    hold_ms: float | None = None
    repeat_ms: float | None = None
    cooldown_ms: float = 500.0


@dataclass(frozen=True)
class Config:
    camera: CameraConfig = CameraConfig()
    recognition: RecognitionConfig = RecognitionConfig()
    motion: MotionConfig = MotionConfig()
    arming: ArmingConfig = ArmingConfig()
    idle: IdleConfig = IdleConfig()
    feedback: FeedbackConfig = FeedbackConfig()
    bindings: tuple[Binding, ...] = field(default_factory=tuple)


def default_config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "handsign" / "config.toml"


def default_config_text() -> str:
    return resources.files("handsign").joinpath("default_config.toml").read_text("utf-8")


def _section(cls: type, data: Any, name: str):
    """Build dataclass `cls` from a TOML table, rejecting unknown keys and wrong types."""
    if not isinstance(data, dict):
        raise ConfigError(f"[{name}] must be a table")
    fields = {f.name: f for f in dataclasses.fields(cls)}
    unknown = set(data) - set(fields)
    if unknown:
        raise ConfigError(f"[{name}] unknown keys: {sorted(unknown)} (known: {sorted(fields)})")
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        default = getattr(cls(), key)
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, float):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            value = float(value) if ok else value
        elif isinstance(default, int) and key != "device":
            ok = isinstance(value, int) and not isinstance(value, bool)
        else:
            ok = isinstance(value, (int, str)) if key == "device" else isinstance(value, str)
        if not ok:
            raise ConfigError(f"[{name}] {key} = {value!r}: expected {type(default).__name__}")
        kwargs[key] = value
    return cls(**kwargs)


def _gesture_ok(gesture: str) -> bool:
    if gesture in POSES or gesture in SWIPES:
        return True
    pose, sep, swipe = gesture.partition("+")
    return bool(sep) and pose in POSES and swipe in SWIPES


def _binding(raw: Any, index: int) -> Binding:
    where = f"[[binding]] #{index + 1}"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a table")
    unknown = set(raw) - {"gesture", "action", "hand", "hold_ms", "repeat_ms", "cooldown_ms"}
    if unknown:
        raise ConfigError(f"{where} unknown keys: {sorted(unknown)}")
    gesture = raw.get("gesture")
    if not isinstance(gesture, str) or not _gesture_ok(gesture):
        raise ConfigError(
            f"{where} gesture = {gesture!r}: expected a pose ({', '.join(POSES)}), "
            f"a swipe ({', '.join(SWIPES)}) or '<pose>+<swipe>'"
        )
    where = f"{where} ({gesture})"
    hand = raw.get("hand")
    if hand not in (None, "left", "right"):
        raise ConfigError(f'{where} hand must be "left" or "right"')
    numbers: dict[str, float] = {}
    for key in ("hold_ms", "repeat_ms", "cooldown_ms"):
        if key in raw:
            value = raw[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ConfigError(f"{where} {key} must be a non-negative number")
            numbers[key] = float(value)
    if "swipe" in gesture and ("hold_ms" in numbers or "repeat_ms" in numbers):
        raise ConfigError(f"{where} hold_ms / repeat_ms only apply to static poses")
    if "action" not in raw:
        raise ConfigError(f"{where} is missing 'action'")
    try:
        action = build_action(raw["action"])
    except ActionError as err:
        raise ConfigError(f"{where} {err}") from err
    return Binding(gesture=gesture, action=action, hand=hand, **numbers)


def parse_config(data: dict[str, Any]) -> Config:
    known = {"camera", "recognition", "motion", "arming", "idle", "feedback", "binding"}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"unknown top-level keys: {sorted(unknown)}")

    recognition_raw = dict(data.get("recognition", {}))
    thresholds = _section(
        PoseThresholds, recognition_raw.pop("thresholds", {}), "recognition.thresholds"
    )
    recognition = dataclasses.replace(
        _section(RecognitionConfig, recognition_raw, "recognition"), thresholds=thresholds
    )
    arming = _section(ArmingConfig, data.get("arming", {}), "arming")
    if arming.enabled and arming.pose not in POSES:
        raise ConfigError(f"[arming] pose = {arming.pose!r} is not a known pose")
    if arming.disarm_pose and arming.disarm_pose not in POSES:
        raise ConfigError(f"[arming] disarm_pose = {arming.disarm_pose!r} is not a known pose")

    raw_bindings = data.get("binding", [])
    if not isinstance(raw_bindings, list):
        raise ConfigError("'binding' must be an array of tables: use [[binding]]")

    return Config(
        camera=_section(CameraConfig, data.get("camera", {}), "camera"),
        recognition=recognition,
        motion=_section(MotionConfig, data.get("motion", {}), "motion"),
        arming=arming,
        idle=_section(IdleConfig, data.get("idle", {}), "idle"),
        feedback=_section(FeedbackConfig, data.get("feedback", {}), "feedback"),
        bindings=tuple(_binding(b, i) for i, b in enumerate(raw_bindings)),
    )


def load_config(path: Path | None = None) -> Config:
    """Load `path`, or the user's config, or the built-in defaults if there is none."""
    if path is None:
        path = default_config_path()
        text = path.read_text("utf-8") if path.exists() else default_config_text()
    else:
        try:
            text = path.read_text("utf-8")
        except OSError as err:
            raise ConfigError(f"cannot read {path}: {err}") from err
    try:
        return parse_config(tomllib.loads(text))
    except tomllib.TOMLDecodeError as err:
        raise ConfigError(f"{path}: {err}") from err
