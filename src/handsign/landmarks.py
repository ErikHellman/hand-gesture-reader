"""MediaPipe HandLandmarker wrapper: BGR frame in, list[Hand] out."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import urllib.request
from pathlib import Path

import numpy as np

from .types import Hand

log = logging.getLogger(__name__)

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)


def cache_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "handsign"


def ensure_model(path: Path | None = None) -> Path:
    path = path or cache_dir() / "hand_landmarker.task"
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading hand landmark model to %s", path)
    tmp = path.with_suffix(".part")
    # Short timeout: on hosts with broken IPv6 every unreachable address costs one timeout
    # before urllib falls back to IPv4.
    with urllib.request.urlopen(MODEL_URL, timeout=5) as response, open(tmp, "wb") as out:
        shutil.copyfileobj(response, out)
    tmp.replace(path)
    return path


class HandTracker:
    """Detects hands in BGR frames.

    mirrored: whether the frames passed in are already flipped horizontally (selfie view).
    MediaPipe's handedness labels assume a mirrored image, so they are swapped otherwise.
    """

    def __init__(
        self,
        *,
        max_hands: int = 1,
        min_confidence: float = 0.6,
        mirrored: bool = True,
        video: bool = True,
        model_path: Path | None = None,
    ) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        self._video = video
        self._mirrored = mirrored
        self._last_ts = -1
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ensure_model(model_path))),
            running_mode=vision.RunningMode.VIDEO if video else vision.RunningMode.IMAGE,
            num_hands=max_hands,
            min_hand_detection_confidence=min_confidence,
            min_hand_presence_confidence=min_confidence,
            min_tracking_confidence=min_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)

    def detect(self, frame_bgr: np.ndarray, timestamp_ms: int = 0) -> list[Hand]:
        import cv2

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        if self._video:
            # Timestamps must be strictly increasing.
            timestamp_ms = max(timestamp_ms, self._last_ts + 1)
            self._last_ts = timestamp_ms
            result = self._landmarker.detect_for_video(image, timestamp_ms)
        else:
            result = self._landmarker.detect(image)

        height, width = frame_bgr.shape[:2]
        aspect = width / height
        hands = []
        for lms, world, handed in zip(
            result.hand_landmarks, result.hand_world_landmarks, result.handedness
        ):
            img = np.array([[p.x * aspect, p.y, p.z * aspect] for p in lms], dtype=np.float64)
            wld = np.array([[p.x, p.y, p.z] for p in world], dtype=np.float64)
            label = handed[0].category_name.lower()
            if not self._mirrored:
                label = "left" if label == "right" else "right"
            hands.append(Hand(img, wld, label, float(handed[0].score)))
        return hands

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> HandTracker:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
