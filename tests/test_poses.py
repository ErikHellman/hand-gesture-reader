import numpy as np
import pytest

from conftest import make_hand
from handsign.poses import POSES, PoseThresholds, classify

CASES = [
    ("open_palm", dict(fingers="IMRP", thumb="out")),
    ("open_palm", dict(fingers="IMRP", thumb="neutral")),
    ("four", dict(fingers="IMRP", thumb="tucked")),
    ("three", dict(fingers="IMR", thumb="tucked")),
    ("peace", dict(fingers="IM", thumb="tucked")),
    ("peace", dict(fingers="IM", thumb="out")),
    ("rock", dict(fingers="IP", thumb="tucked")),
    ("point", dict(fingers="I", thumb="neutral")),
    ("call", dict(fingers="P", thumb="out")),
    ("fist", dict(fingers="", thumb="tucked")),
    ("fist", dict(fingers="", thumb="neutral")),
    ("thumbs_up", dict(fingers="", thumb="out", rotate_deg=45)),
    ("thumbs_down", dict(fingers="", thumb="out", rotate_deg=225)),
    ("none", dict(fingers="", thumb="out", rotate_deg=135)),  # thumb sideways
    ("ok", dict(fingers="MRP", pinch=True)),
    ("pinch", dict(fingers="", pinch=True)),
    ("none", dict(fingers="MR", thumb="tucked")),
]


@pytest.mark.parametrize("expected, kwargs", CASES)
def test_classify(expected, kwargs):
    assert classify(make_hand(**kwargs)).name == expected


def test_every_pose_is_covered():
    assert {name for name, _ in CASES} - {"none"} == set(POSES)


@pytest.mark.parametrize("rotate_deg", [-60, -30, 0, 30, 60, 180])
def test_rotation_invariant(rotate_deg):
    assert classify(make_hand("IM", "tucked", rotate_deg=rotate_deg)).name == "peace"


def test_scale_invariant():
    hand = make_hand("I", "tucked")
    scaled = type(hand)(hand.image * 0.4, hand.world * 1.3, hand.handedness)
    assert classify(scaled).name == "point"


def test_fingers_reported():
    pose = classify(make_hand("IP", "out"))
    assert pose.fingers == (True, True, False, False, True)
    assert 0.0 <= pose.confidence <= 1.0


def test_thresholds_are_used():
    hand = make_hand("IMRP", "neutral")
    assert classify(hand, PoseThresholds(thumb_tucked=1.0)).name == "four"


def test_degenerate_hand():
    hand = make_hand()
    flat = type(hand)(np.zeros((21, 3)), np.zeros((21, 3)), "left")
    assert classify(flat).name == "none"
