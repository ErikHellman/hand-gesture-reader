"""The daemon: camera loop, pause / resume, idle throttling, optional preview and recording."""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from pathlib import Path
from typing import IO

from .actions import keys
from .actions.keys import KeysAction
from .camera import Camera, CameraError
from .config import Config
from .control import ControlServer
from .dispatcher import Dispatcher
from .feedback import Notifier
from .landmarks import HandTracker
from .recognizer import FrameState, Recognizer

log = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        cfg: Config,
        *,
        preview: bool = False,
        record: Path | None = None,
        dry_run: bool = False,
    ) -> None:
        self.cfg = cfg
        self._preview_enabled = preview
        self._record_path = record
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._wake = threading.Event()
        self._notifier = Notifier(cfg.feedback.notify)
        self._dispatcher = Dispatcher(() if dry_run else cfg.bindings)
        self._recognizer = Recognizer(cfg, self._dispatcher, self._notifier.notify)
        self._last_state = FrameState()

    # -- control -------------------------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _control(self, command: str) -> dict:
        if command == "pause" or (command == "toggle" and not self._paused.is_set()):
            self._paused.set()
        elif command in ("resume", "toggle"):
            self._paused.clear()
        elif command == "quit":
            self.stop()
        self._wake.set()
        return {
            "ok": True,
            "paused": self._paused.is_set(),
            "armed": self._recognizer.armed and not self._paused.is_set(),
            "pose": self._last_state.stable,
        }

    # -- main loop -----------------------------------------------------------------------

    def run(self) -> int:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self.stop())

        if any(isinstance(b.action, KeysAction) for b in self._dispatcher.bindings):
            keys.get_backend().open()

        control = ControlServer(self._control)
        camera = Camera(self.cfg.camera)
        preview = None
        recording: IO[str] | None = None
        try:
            if self._preview_enabled:
                from .preview import Preview, prepare_environment

                prepare_environment()
                preview = Preview()
            if self._record_path:
                recording = open(self._record_path, "w", encoding="utf-8")
            with HandTracker(
                max_hands=self.cfg.recognition.max_hands,
                min_confidence=self.cfg.recognition.min_confidence,
                mirrored=self.cfg.camera.mirror,
            ) as tracker:
                self._loop(camera, tracker, preview, recording)
        except CameraError as err:
            log.error("%s", err)
            return 1
        finally:
            camera.close()
            control.close()
            self._dispatcher.close()
            if preview is not None:
                preview.close()
            if recording is not None:
                recording.close()
        return 0

    def _loop(self, camera: Camera, tracker: HandTracker, preview, recording) -> None:
        idle_cfg = self.cfg.idle
        start = time.monotonic()
        last_hand = start
        was_paused = False
        frames, fps_mark = 0, start

        while not self._stop.is_set():
            if self._paused.is_set():
                if not was_paused:
                    camera.close()
                    self._recognizer.reset()
                    self._last_state = FrameState()
                    self._notifier.notify("paused — camera off")
                    was_paused = True
                self._wake.clear()
                self._wake.wait(timeout=1.0)
                continue
            if was_paused:
                self._notifier.notify("resumed")
                was_paused = False
                last_hand = time.monotonic()

            frame_start = time.monotonic()
            frame = camera.read()
            now = time.monotonic()
            hands = tracker.detect(frame, int((now - start) * 1000))
            state = self._recognizer.process(hands, now)
            self._last_state = state
            if hands:
                last_hand = now

            if recording is not None:
                recording.write(json.dumps(_record(state, now - start)) + "\n")
            if preview is not None and not preview.show(frame, state):
                self.stop()

            frames += 1
            if now - fps_mark >= 30.0:
                log.debug("%.1f fps", frames / (now - fps_mark))
                frames, fps_mark = 0, now

            idle = now - last_hand > idle_cfg.after_s and not state.armed
            if idle and idle_cfg.fps > 0:
                # Sleep the rest of the idle frame interval; a control command wakes us early.
                remaining = 1.0 / idle_cfg.fps - (time.monotonic() - frame_start)
                if remaining > 0:
                    self._wake.clear()
                    self._wake.wait(timeout=remaining)


def _record(state: FrameState, t: float) -> dict:
    entry: dict = {"t": round(t, 4), "stable": state.stable, "armed": state.armed}
    if state.hand is not None and state.pose is not None:
        entry.update(
            hand=state.hand.handedness,
            pose=state.pose.name,
            image=state.hand.image.round(5).tolist(),
            world=state.hand.world.round(5).tolist(),
        )
    if state.events:
        entry["events"] = [e.candidates[0] for e in state.events]
    return entry
