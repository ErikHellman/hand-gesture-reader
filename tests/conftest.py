"""Synthetic hands for camera-free tests."""

from __future__ import annotations

import numpy as np
import pytest

from handsign.types import Hand

# Finger MCP positions in metres; wrist at the origin, fingers pointing up (-y), palm facing
# the camera, thumb on the -x side.
_MCP = {"I": (-0.025, -0.090), "M": (0.0, -0.095), "R": (0.020, -0.088), "P": (0.040, -0.078)}
_THUMB_BASE = [(-0.025, -0.02, 0.0), (-0.045, -0.045, 0.0)]  # CMC, MCP
_THUMB = {
    "out": [(-0.065, -0.065, 0.0), (-0.085, -0.085, 0.0)],  # IP, TIP
    "neutral": [(-0.047, -0.067, 0.0), (-0.045, -0.085, 0.0)],
    "tucked": [(-0.030, -0.060, 0.02), (0.0, -0.070, 0.03)],
}
_EXTENDED = [(0.0, -0.040, 0.0), (0.0, -0.065, 0.0), (0.0, -0.085, 0.0)]  # PIP, DIP, TIP offsets
_CURLED = [(0.0, -0.030, 0.02), (0.0, -0.010, 0.04), (0.0, 0.010, 0.035)]
_PINCH_TIP = (-0.035, -0.130, 0.04)


def make_hand(
    fingers: str = "IMRP",
    thumb: str = "neutral",
    *,
    pinch: bool = False,
    rotate_deg: float = 0.0,
    center: tuple[float, float] = (0.66, 0.6),
    scale: float = 2.0,
    handedness: str = "right",
) -> Hand:
    """fingers: letters of the extended fingers among I, M, R, P."""
    points = [(0.0, 0.0, 0.0), *_THUMB_BASE, *_THUMB[thumb]]
    for name, (x, y) in _MCP.items():
        offsets = _EXTENDED if name in fingers else _CURLED
        points.append((x, y, 0.0))
        points.extend((x + dx, y + dy, dz) for dx, dy, dz in offsets)
    world = np.array(points, dtype=np.float64)
    if pinch:
        world[8] = _PINCH_TIP
        world[7] = (-0.03, -0.115, 0.02)
        world[4] = np.array(_PINCH_TIP) + (0.004, 0.0, 0.0)
        world[3] = (-0.045, -0.09, 0.02)

    a = np.radians(rotate_deg)
    rotation = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    world = world @ rotation.T
    image = world * scale
    image[:, :2] += np.array(center) - image[[0, 5, 9, 13, 17], :2].mean(axis=0)
    return Hand(image=image, world=world, handedness=handedness)


@pytest.fixture
def hand_factory():
    return make_hand
