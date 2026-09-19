"""Rule-based static pose classification from hand landmarks.

All measurements use MediaPipe's metric world landmarks, normalised by hand size
(wrist to middle-finger MCP), so they are independent of distance to the camera and
largely independent of hand rotation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .types import FINGERS, INDEX, MIDDLE, PINKY, THUMB, WRIST, Hand, Pose


@dataclass(frozen=True)
class PoseThresholds:
    # Finger: |tip - wrist| / |mcp - wrist|. Curled ≈ 0.7–1.2, extended ≈ 1.45–2.4.
    finger_reach: float = 1.3
    # Thumb: |thumb tip - pinky mcp| / hand size. Out ≈ 1.3+, across the palm ≈ 0.6–0.75,
    # resting alongside an open hand ≈ 0.9.
    thumb_out: float = 1.1
    thumb_tucked: float = 0.8
    # |thumb tip - index tip| / hand size below which the two are pinched together.
    pinch_distance: float = 0.25
    # Max deviation from vertical for thumbs_up / thumbs_down.
    thumb_direction_deg: float = 50.0


OUT, NEUTRAL, TUCKED = "out", "neutral", "tucked"

# (allowed thumb states, (index, middle, ring, pinky)). First match wins.
_ANY = (OUT, NEUTRAL, TUCKED)
_RULES: tuple[tuple[str, tuple[str, ...], tuple[bool, bool, bool, bool]], ...] = (
    ("open_palm", (OUT, NEUTRAL), (True, True, True, True)),
    ("four", (TUCKED,), (True, True, True, True)),
    ("three", _ANY, (True, True, True, False)),
    ("peace", _ANY, (True, True, False, False)),
    ("rock", _ANY, (True, False, False, True)),
    ("point", _ANY, (True, False, False, False)),
    ("call", (OUT,), (False, False, False, True)),
    ("thumb", (OUT,), (False, False, False, False)),  # refined to thumbs_up / thumbs_down
    ("fist", (NEUTRAL, TUCKED), (False, False, False, False)),
)

POSES = (
    "open_palm", "four", "three", "peace", "rock", "point", "call",
    "thumbs_up", "thumbs_down", "fist", "ok", "pinch",
)  # fmt: skip


def _dist(points: np.ndarray, a: int, b: int) -> float:
    return float(np.linalg.norm(points[a] - points[b]))


def classify(hand: Hand, th: PoseThresholds = PoseThresholds()) -> Pose:
    w = hand.world
    size = _dist(w, MIDDLE[0], WRIST)
    if size < 1e-6:
        return Pose("none", 0.0, (False,) * 5, False)

    margins: list[float] = []
    states: list[bool] = []
    for mcp, _pip, _dip, tip in FINGERS:
        reach = _dist(w, tip, WRIST) / max(_dist(w, mcp, WRIST), 1e-6)
        states.append(reach > th.finger_reach)
        margins.append(abs(reach - th.finger_reach) / 0.3)

    thumb_spread = _dist(w, THUMB[3], PINKY[0]) / size
    if thumb_spread > th.thumb_out:
        thumb = OUT
    elif thumb_spread < th.thumb_tucked:
        thumb = TUCKED
    else:
        thumb = NEUTRAL

    pinch = _dist(w, THUMB[3], INDEX[3]) / size < th.pinch_distance
    fingers = (thumb == OUT, *states)
    confidence = float(np.clip(min(margins), 0.0, 1.0))

    if pinch:
        name = "ok" if all(states[1:]) else "pinch"
        return Pose(name, confidence, fingers, True)

    for name, thumbs, rule in _RULES:
        if thumb in thumbs and rule == tuple(states):
            if name == "thumb":
                name = _thumb_direction(hand, th)
            return Pose(name, confidence, fingers, False)
    return Pose("none", confidence, fingers, False)


def _thumb_direction(hand: Hand, th: PoseThresholds) -> str:
    v = hand.image[THUMB[3], :2] - hand.image[THUMB[1], :2]
    norm = np.linalg.norm(v)
    if norm < 1e-9:
        return "none"
    # Image y grows downwards: up is -y.
    deviation = np.degrees(np.arccos(np.clip(-v[1] / norm, -1.0, 1.0)))
    if deviation < th.thumb_direction_deg:
        return "thumbs_up"
    if deviation > 180.0 - th.thumb_direction_deg:
        return "thumbs_down"
    return "none"
