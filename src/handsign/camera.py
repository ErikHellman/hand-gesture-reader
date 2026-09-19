"""Webcam capture through OpenCV (V4L2 / AVFoundation / MSMF depending on the OS)."""

from __future__ import annotations

import logging
import sys

import cv2
import numpy as np

from .config import CameraConfig

log = logging.getLogger(__name__)


class CameraError(RuntimeError):
    pass


class Camera:
    def __init__(self, cfg: CameraConfig) -> None:
        self.cfg = cfg
        self._cap: cv2.VideoCapture | None = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None

    def open(self) -> None:
        if self._cap is not None:
            return
        backend = cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.cfg.device, backend)
        if not cap.isOpened():
            cap.release()
            raise CameraError(f"cannot open camera {self.cfg.device!r}")
        # MJPG first: most UVC cameras only reach 30 fps at useful sizes when compressed.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
        cap.set(cv2.CAP_PROP_FPS, self.cfg.fps)
        # Keep latency low: never queue more than one frame.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap = cap
        log.info(
            "camera %r open: %dx%d @ %.0f fps",
            self.cfg.device,
            cap.get(cv2.CAP_PROP_FRAME_WIDTH),
            cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
            cap.get(cv2.CAP_PROP_FPS),
        )

    def read(self) -> np.ndarray:
        if self._cap is None:
            self.open()
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise CameraError("failed to read a frame from the camera")
        return cv2.flip(frame, 1) if self.cfg.mirror else frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            log.info("camera released")


def list_cameras(limit: int = 8) -> list[tuple[int, int, int]]:
    """Probe camera indices; returns (index, width, height) for each that delivers frames."""
    found = []
    backend = cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_ANY
    for index in range(limit):
        cap = cv2.VideoCapture(index, backend)
        try:
            if cap.isOpened() and cap.read()[0]:
                found.append(
                    (
                        index,
                        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                    )
                )
        finally:
            cap.release()
    return found
