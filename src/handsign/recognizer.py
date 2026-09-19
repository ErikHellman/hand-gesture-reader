"""Camera-independent gesture logic: hands per frame in, dispatched actions out."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .config import Config
from .dispatcher import Dispatcher
from .motion import SwipeDetector
from .poses import classify
from .temporal import HoldSpec, HoldTracker, PoseStabilizer
from .types import GestureEvent, Hand, Pose


@dataclass
class FrameState:
    """What happened in one frame; used by the preview and the recorder."""

    hand: Hand | None = None
    pose: Pose | None = None
    stable: str = "none"
    armed: bool = False
    events: list[GestureEvent] = field(default_factory=list)
    fired: list[str] = field(default_factory=list)


class Recognizer:
    def __init__(
        self,
        cfg: Config,
        dispatcher: Dispatcher,
        notify: Callable[[str], None] = lambda message: None,
    ) -> None:
        self.cfg = cfg
        self.dispatcher = dispatcher
        self._notify = notify
        rec = cfg.recognition
        self._stabilizer = PoseStabilizer(rec.vote_window_ms, rec.vote_ratio)
        self._swipes = SwipeDetector(cfg.motion)
        self._hold = HoldTracker(HoldSpec(rec.hold_ms))
        self._armed = not cfg.arming.enabled
        self._armed_until = 0.0
        self._last_seen = 0.0
        self._update_hold_specs()

    @property
    def armed(self) -> bool:
        return self._armed

    def _update_hold_specs(self) -> None:
        specs: dict[str, HoldSpec] = {}
        for b in self.cfg.bindings:
            if "swipe" in b.gesture or (b.hold_ms is None and b.repeat_ms is None):
                continue
            specs[b.gesture] = HoldSpec(
                b.hold_ms if b.hold_ms is not None else self.cfg.recognition.hold_ms, b.repeat_ms
            )
        arming = self.cfg.arming
        if arming.enabled and not self._armed:
            specs[arming.pose] = HoldSpec(arming.hold_ms)
        self._hold.overrides = specs

    def _set_armed(self, armed: bool, t: float, reason: str = "") -> None:
        if armed:
            self._armed_until = t + self.cfg.arming.timeout_s
        if armed == self._armed:
            return
        self._armed = armed
        self._update_hold_specs()
        self._notify("armed — ready for gestures" if armed else f"disarmed{reason}")

    def reset(self) -> None:
        """Forget all tracking state (camera paused)."""
        self._stabilizer.reset()
        self._hold.reset()
        self._swipes.reset()
        if self.cfg.arming.enabled:
            self._armed = False
            self._update_hold_specs()

    def process(self, hands: list[Hand], t: float) -> FrameState:
        arming = self.cfg.arming
        if arming.enabled and self._armed and t > self._armed_until:
            self._set_armed(False, t, " (timeout)")

        state = FrameState(armed=self._armed)
        if not hands:
            if t - self._last_seen > self.cfg.motion.gap_ms / 1000.0:
                self._stabilizer.reset()
                self._hold.reset()
            return state

        self._last_seen = t
        hand = max(hands, key=lambda h: h.size)
        pose = classify(hand, self.cfg.recognition.thresholds)
        state.hand, state.pose = hand, pose

        swipe = self._swipes.update(hand.center, hand.size, pose.name, t)
        moving = self._swipes.speed() > self.cfg.recognition.max_pose_speed
        stable, since = self._stabilizer.update("none" if moving else pose.name, t)
        state.stable = stable

        if swipe is not None:
            state.events.append(GestureEvent(swipe.name, hand.handedness, pose=swipe.pose))
            self._stabilizer.reset()
            self._hold.reset()
        else:
            held = self._hold.update(stable, since, t)
            if held is not None:
                state.events.append(GestureEvent(held.pose, hand.handedness, repeat=held.repeat))

        for event in state.events:
            self._handle(event, t, state)
        state.armed = self._armed
        return state

    def _handle(self, event: GestureEvent, t: float, state: FrameState) -> None:
        arming = self.cfg.arming
        if arming.enabled:
            is_pose = event.pose is None
            if not self._armed:
                if is_pose and event.name == arming.pose:
                    self._set_armed(True, t)
                return
            if is_pose and event.name == arming.disarm_pose:
                self._set_armed(False, t)
                return
        binding = self.dispatcher.dispatch(event, t)
        if binding is not None:
            state.fired.append(binding.gesture)
            if arming.enabled:
                self._set_armed(True, t)  # renew the timeout
            if self.cfg.feedback.notify_gestures and not event.repeat:
                self._notify(binding.gesture)
