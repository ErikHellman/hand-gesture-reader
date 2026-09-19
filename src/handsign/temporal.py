"""Turns noisy per-frame pose labels into discrete hold / repeat events."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass


class PoseStabilizer:
    """Sliding-window majority vote over per-frame pose names.

    update() returns the stable pose ("none" if there is no clear winner) and the time at
    which it became stable.
    """

    def __init__(self, window_ms: float = 300.0, ratio: float = 0.7) -> None:
        self.window = window_ms / 1000.0
        self.ratio = ratio
        self._samples: deque[tuple[float, str]] = deque()
        self._stable = "none"
        self._since = 0.0

    def reset(self) -> None:
        self._samples.clear()
        self._stable = "none"

    def update(self, pose: str, t: float) -> tuple[str, float]:
        self._samples.append((t, pose))
        while self._samples and t - self._samples[0][0] > self.window:
            self._samples.popleft()

        winner = "none"
        # Need at least half a window of history before trusting the vote.
        if len(self._samples) >= 3 and t - self._samples[0][0] >= self.window * 0.5:
            name, count = Counter(p for _, p in self._samples).most_common(1)[0]
            if count / len(self._samples) >= self.ratio:
                winner = name

        if winner != self._stable:
            self._stable = winner
            self._since = t
        return self._stable, self._since


@dataclass(frozen=True)
class HoldSpec:
    hold_ms: float
    repeat_ms: float | None = None


@dataclass(frozen=True)
class HoldEvent:
    pose: str
    repeat: bool


class HoldTracker:
    """Fires once when a stable pose has been held long enough, then optionally repeats.

    Hold and repeat times are looked up per pose so bindings can override the default.
    """

    def __init__(self, default: HoldSpec, overrides: dict[str, HoldSpec] | None = None) -> None:
        self.default = default
        self.overrides = dict(overrides or {})
        self._pose = "none"
        self._fired_at: float | None = None

    def reset(self) -> None:
        self._pose = "none"
        self._fired_at = None

    def update(self, stable: str, since: float, t: float) -> HoldEvent | None:
        if stable != self._pose:
            self._pose = stable
            self._fired_at = None
        if stable == "none":
            return None

        spec = self.overrides.get(stable, self.default)
        if self._fired_at is None:
            if (t - since) * 1000.0 >= spec.hold_ms:
                self._fired_at = t
                return HoldEvent(stable, repeat=False)
        elif spec.repeat_ms and (t - self._fired_at) * 1000.0 >= spec.repeat_ms:
            self._fired_at = t
            return HoldEvent(stable, repeat=True)
        return None
