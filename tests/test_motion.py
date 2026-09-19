import numpy as np
import pytest

from handsign.motion import MotionConfig, SwipeDetector

FRAME = 1 / 30
SIZE = 0.2


def move(detector, start, velocity, frames, t0=0.0, pose="open_palm"):
    """velocity in hand sizes per second. Returns (swipes, end position, end time)."""
    swipes = []
    position = np.array(start, dtype=float)
    t = t0
    for _ in range(frames):
        position = position + np.array(velocity) * SIZE * FRAME
        t += FRAME
        swipe = detector.update(position, SIZE, pose, t)
        if swipe:
            swipes.append(swipe)
    return swipes, position, t


@pytest.mark.parametrize(
    "velocity, expected",
    [
        ((8, 0), "swipe_right"),
        ((-8, 0), "swipe_left"),
        ((0, -8), "swipe_up"),
        ((0, 8), "swipe_down"),
    ],
)
def test_directions(velocity, expected):
    swipes, _, _ = move(SwipeDetector(), (0.6, 0.5), velocity, 10)
    assert [s.name for s in swipes] == [expected]
    assert swipes[0].pose == "open_palm"


def test_slow_motion_is_not_a_swipe():
    swipes, _, _ = move(SwipeDetector(), (0.2, 0.5), (2, 0), 60)
    assert swipes == []


def test_diagonal_is_rejected():
    swipes, _, _ = move(SwipeDetector(), (0.2, 0.2), (8, 6), 12)
    assert swipes == []


def test_return_stroke_is_ignored():
    detector = SwipeDetector(MotionConfig(cooldown_ms=700))
    swipes, position, t = move(detector, (0.3, 0.5), (8, 0), 10)
    back, _, _ = move(detector, position, (-8, 0), 10, t0=t)
    assert len(swipes) == 1 and back == []


def test_tracking_gap_resets_trajectory():
    detector = SwipeDetector()
    detector.update(np.array([0.1, 0.5]), SIZE, "point", 0.0)
    detector.update(np.array([0.1, 0.5]), SIZE, "point", FRAME)
    # The hand reappears far away after a gap: a jump, not a swipe.
    assert detector.update(np.array([0.9, 0.5]), SIZE, "point", 1.0) is None
    assert detector.update(np.array([0.9, 0.5]), SIZE, "point", 1.0 + FRAME) is None


def test_speed():
    detector = SwipeDetector(MotionConfig(enabled=False))
    move(detector, (0.2, 0.5), (3, 0), 5)
    assert detector.speed() == pytest.approx(3.0, rel=1e-6)
