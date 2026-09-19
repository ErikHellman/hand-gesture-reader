"""Dynamic gesture detection (swipes) from the palm-centre trajectory."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MotionConfig:
    enabled: bool = True
    window_ms: float = 400.0  # a swipe must complete within this time
    min_distance: float = 1.5  # travel along the main axis, in hand sizes
    axis_ratio: float = 2.0  # main-axis travel must exceed cross-axis travel by this factor
    cooldown_ms: float = 700.0  # ignore motion after a swipe (the hand moving back)
    gap_ms: float = 200.0  # tracking gap that invalidates the trajectory


@dataclass(frozen=True)
class Swipe:
    name: str  # swipe_left / swipe_right / swipe_up / swipe_down
    pose: str  # most common per-frame pose during the swipe


class SwipeDetector:
    def __init__(self, cfg: MotionConfig = MotionConfig()) -> None:
        self.cfg = cfg
        self._track: deque[tuple[float, np.ndarray, float, str]] = deque()
        self._blocked_until = 0.0

    def reset(self) -> None:
        self._track.clear()

    def speed(self) -> float:
        """Current palm speed in hand sizes per second (0 if unknown)."""
        if len(self._track) < 2:
            return 0.0
        (t0, c0, _, _), (t1, c1, s1, _) = self._track[-2], self._track[-1]
        if t1 <= t0 or s1 <= 0:
            return 0.0
        return float(np.linalg.norm(c1 - c0) / s1 / (t1 - t0))

    def update(self, center: np.ndarray, size: float, pose: str, t: float) -> Swipe | None:
        cfg = self.cfg
        if self._track and (t - self._track[-1][0]) * 1000.0 > cfg.gap_ms:
            self._track.clear()
        self._track.append((t, np.asarray(center, dtype=np.float64), size, pose))
        while (t - self._track[0][0]) * 1000.0 > cfg.window_ms:
            self._track.popleft()

        if not cfg.enabled or t < self._blocked_until or len(self._track) < 3:
            return None

        mean_size = float(np.mean([s for _, _, s, _ in self._track]))
        if mean_size <= 0:
            return None
        # Best displacement ending at the newest sample, from any sample in the window.
        newest = self._track[-1][1]
        deltas = np.array([newest - c for _, c, _, _ in self._track]) / mean_size
        main = np.abs(deltas).max(axis=1)
        i = int(main.argmax())
        dx, dy = deltas[i]
        ax, ay = abs(dx), abs(dy)
        if max(ax, ay) < cfg.min_distance or max(ax, ay) < cfg.axis_ratio * min(ax, ay):
            return None

        if ax > ay:
            name = "swipe_right" if dx > 0 else "swipe_left"
        else:
            name = "swipe_down" if dy > 0 else "swipe_up"
        poses = Counter(p for _, _, _, p in list(self._track)[i:])
        pose = poses.most_common(1)[0][0]
        self._track.clear()
        self._blocked_until = t + cfg.cooldown_ms / 1000.0
        return Swipe(name, pose)
