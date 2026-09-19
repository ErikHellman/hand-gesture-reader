"""Debug window: camera frame with landmarks, finger states and recognised gestures."""

from __future__ import annotations

import os
import sys
import time

import cv2
import numpy as np

from .recognizer import FrameState

_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
    (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)  # fmt: skip
_WINDOW = "handsign"
_GREEN, _RED, _WHITE, _YELLOW = (80, 220, 80), (80, 80, 230), (255, 255, 255), (60, 220, 250)


def prepare_environment() -> None:
    """OpenCV's bundled Qt only ships the xcb plugin; use XWayland on Wayland sessions."""
    if sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")


class Preview:
    def __init__(self) -> None:
        cv2.namedWindow(_WINDOW, cv2.WINDOW_NORMAL)
        self._last_fired = ""
        self._last_fired_at = 0.0
        self._frame_times: list[float] = []

    def show(self, frame: np.ndarray, state: FrameState, *, paused: bool = False) -> bool:
        """Draw and display. Returns False when the user asked to quit (q / Esc / closed)."""
        now = time.monotonic()
        self._frame_times = [t for t in self._frame_times if now - t < 1.0] + [now]
        height = frame.shape[0]

        if state.hand is not None:
            points = (state.hand.image[:, :2] * height).astype(int)
            for a, b in _CONNECTIONS:
                cv2.line(frame, tuple(points[a]), tuple(points[b]), _WHITE, 1, cv2.LINE_AA)
            for point in points:
                cv2.circle(frame, tuple(point), 3, _GREEN, -1, cv2.LINE_AA)

        for event in state.events:
            label = event.candidates[0] + ("" if state.fired else " (no action)")
            self._last_fired, self._last_fired_at = label, now

        lines = [(f"{len(self._frame_times)} fps", _WHITE)]
        if paused:
            lines.append(("PAUSED", _RED))
        else:
            lines.append(("ARMED" if state.armed else "disarmed", _GREEN if state.armed else _RED))
        if state.pose is not None:
            fingers = "".join(c if on else "-" for c, on in zip("TIMRP", state.pose.fingers))
            pose = f"{state.pose.name} {state.pose.confidence:.2f} [{fingers}]"
            lines.append((f"{pose} {state.hand.handedness}", _WHITE))
            lines.append((f"stable: {state.stable}", _WHITE))
        if now - self._last_fired_at < 1.5:
            lines.append((f"> {self._last_fired}", _YELLOW))
        for i, (text, color) in enumerate(lines):
            origin = (10, 24 + 24 * i)
            cv2.putText(
                frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA
            )
            cv2.putText(frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)

        cv2.imshow(_WINDOW, frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            return False
        return cv2.getWindowProperty(_WINDOW, cv2.WND_PROP_VISIBLE) >= 1

    def close(self) -> None:
        cv2.destroyAllWindows()
