"""Plain data types shared by the vision-independent parts of the pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# MediaPipe hand landmark indices.
WRIST = 0
THUMB = (1, 2, 3, 4)  # CMC, MCP, IP, TIP
INDEX = (5, 6, 7, 8)  # MCP, PIP, DIP, TIP
MIDDLE = (9, 10, 11, 12)
RING = (13, 14, 15, 16)
PINKY = (17, 18, 19, 20)
FINGERS = (INDEX, MIDDLE, RING, PINKY)


@dataclass(frozen=True)
class Hand:
    """One detected hand.

    image: (21, 3) landmarks in units of image height (x is scaled by the aspect ratio, so
           distances are isotropic); y grows downwards. Coordinates are as the user sees them
           in the (optionally mirrored) frame.
    world: (21, 3) landmarks in metres, origin at the hand's geometric centre.
    handedness: "left" or "right" — the user's actual hand.
    """

    image: np.ndarray
    world: np.ndarray
    handedness: str
    score: float = 1.0

    @property
    def size(self) -> float:
        """Hand size in image units: wrist to middle-finger MCP."""
        return float(np.linalg.norm(self.image[MIDDLE[0], :2] - self.image[WRIST, :2]))

    @property
    def center(self) -> np.ndarray:
        """Palm centre in image units (x, y)."""
        idx = [WRIST, INDEX[0], MIDDLE[0], RING[0], PINKY[0]]
        return self.image[idx, :2].mean(axis=0)


@dataclass(frozen=True)
class Pose:
    name: str  # "none" when nothing matched
    confidence: float
    fingers: tuple[bool, bool, bool, bool, bool]  # thumb, index, middle, ring, pinky extended
    pinch: bool


@dataclass(frozen=True)
class GestureEvent:
    """A recognised gesture ready to be dispatched.

    name: pose name ("peace") or motion name ("swipe_left").
    pose: for motion events, the pose held during the motion ("open_palm"); else None.
    """

    name: str
    hand: str
    pose: str | None = None
    repeat: bool = False

    @property
    def candidates(self) -> list[str]:
        """Binding names to try, most specific first."""
        if self.pose and self.pose != "none":
            return [f"{self.pose}+{self.name}", self.name]
        return [self.name]
