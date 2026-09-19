"""End-to-end tests of the camera-independent pipeline with synthetic hands."""

import dataclasses
import threading

import numpy as np
import pytest

from conftest import make_hand
from handsign.config import ArmingConfig, Binding, Config
from handsign.dispatcher import Dispatcher
from handsign.recognizer import Recognizer
from handsign.types import GestureEvent

FRAME = 1 / 30


class FakeAction:
    def __init__(self, name):
        self.name = name
        self.runs = 0
        self.done = threading.Event()

    def run(self):
        self.runs += 1
        self.done.set()

    def describe(self):
        return self.name


class Rig:
    def __init__(self, bindings, arming=True):
        cfg = Config(arming=ArmingConfig(enabled=arming), bindings=tuple(bindings))
        self.dispatcher = Dispatcher(cfg.bindings, workers=1)
        self.messages = []
        self.recognizer = Recognizer(cfg, self.dispatcher, self.messages.append)
        self.t = 0.0
        self.fired = []

    def show(self, seconds, **hand):
        """Hold a pose (or no hand, with fingers=None) for a while."""
        for _ in range(round(seconds / FRAME)):
            self.t += FRAME
            hands = [] if hand.get("fingers", "") is None else [make_hand(**hand)]
            self.fired += self.recognizer.process(hands, self.t).fired

    def swipe(self, dx, **hand):
        """Move the hand horizontally by dx hand sizes in 8 frames."""
        size = make_hand(**hand).size
        for i in range(1, 9):
            self.t += FRAME
            center = (0.9 + dx * size * i / 8, 0.6)
            state = self.recognizer.process([make_hand(center=center, **hand)], self.t)
            self.fired += state.fired

    def close(self):
        self.dispatcher.close()


@pytest.fixture
def rig():
    rigs = []

    def build(bindings, **kwargs):
        rigs.append(Rig(bindings, **kwargs))
        return rigs[-1]

    yield build
    for r in rigs:
        r.close()


PEACE = dict(fingers="IM", thumb="tucked")
PALM = dict(fingers="IMRP", thumb="out")
FIST = dict(fingers="", thumb="tucked")
NO_HAND = dict(fingers=None)


def test_pose_fires_once_per_hold(rig):
    action = FakeAction("peace")
    r = rig([Binding("peace", action)], arming=False)
    r.show(1.5, **PEACE)
    assert r.fired == ["peace"]
    assert action.done.wait(2) and action.runs == 1


def test_repeat_binding(rig):
    r = rig([Binding("peace", FakeAction("p"), repeat_ms=250)], arming=False)
    r.show(1.5, **PEACE)
    assert len(r.fired) >= 4


def test_nothing_fires_while_disarmed(rig):
    r = rig([Binding("peace", FakeAction("p"))])
    r.show(1.5, **PEACE)
    assert r.fired == [] and not r.recognizer.armed


def test_arm_then_gesture_then_disarm(rig):
    r = rig([Binding("peace", FakeAction("p")), Binding("open_palm", FakeAction("palm"))])
    r.show(1.0, **PALM)
    assert r.recognizer.armed
    assert r.fired == []  # the arming hold itself must not trigger the open_palm binding
    r.show(1.0, **PEACE)
    assert r.fired == ["peace"]
    r.show(1.0, **FIST)
    assert not r.recognizer.armed
    r.show(1.0, **PEACE)
    assert r.fired == ["peace"]
    assert r.messages == ["armed — ready for gestures", "disarmed"]


def test_arming_times_out(rig):
    r = rig([Binding("peace", FakeAction("p"))])
    r.show(1.0, **PALM)
    r.show(6.0, **NO_HAND)
    assert not r.recognizer.armed
    assert r.messages[-1] == "disarmed (timeout)"


def test_pose_qualified_swipe_beats_generic(rig):
    r = rig(
        [Binding("swipe_right", FakeAction("generic")), Binding("open_palm+swipe_right", FakeAction("palm"))],
        arming=False,
    )  # fmt: skip
    r.swipe(3.0, **PALM)
    assert r.fired == ["open_palm+swipe_right"]
    r.show(1.0, **NO_HAND)
    r.swipe(3.0, **PEACE)
    assert r.fired == ["open_palm+swipe_right", "swipe_right"]


def test_moving_hand_does_not_fire_pose(rig):
    r = rig([Binding("peace", FakeAction("p"), hold_ms=100)], arming=False)
    for _ in range(3):
        r.swipe(1.2, **PEACE)  # fast but too short for a swipe
    assert r.fired == []


def test_hand_specific_binding():
    left, anyhand = FakeAction("left"), FakeAction("any")
    dispatcher = Dispatcher([Binding("peace", anyhand), Binding("peace", left, hand="left")])
    try:
        assert dispatcher.find(GestureEvent("peace", "left")).action is left
        assert dispatcher.find(GestureEvent("peace", "right")).action is anyhand
        assert dispatcher.find(GestureEvent("fist", "right")) is None
    finally:
        dispatcher.close()


def test_cooldown():
    dispatcher = Dispatcher([Binding("peace", FakeAction("p"), cooldown_ms=500)])
    try:
        event = GestureEvent("peace", "right")
        assert dispatcher.dispatch(event, 1.0)
        assert dispatcher.dispatch(event, 1.2) is None
        assert dispatcher.dispatch(dataclasses.replace(event, repeat=True), 1.3)
        assert dispatcher.dispatch(event, 2.0)
    finally:
        dispatcher.close()


def test_failing_action_is_contained():
    class Boom(FakeAction):
        def run(self):
            super().run()
            raise RuntimeError("boom")

    action = Boom("boom")
    dispatcher = Dispatcher([Binding("peace", action)])
    try:
        assert dispatcher.dispatch(GestureEvent("peace", "right"), 1.0)
        assert action.done.wait(2)
    finally:
        dispatcher.close()


def test_largest_hand_wins(rig):
    r = rig([], arming=False)
    near, far = make_hand(**PEACE, scale=2.0), make_hand(**FIST, scale=1.0)
    state = r.recognizer.process([far, near], 0.1)
    assert state.pose.name == "peace"
    assert np.isclose(state.hand.size, near.size)
