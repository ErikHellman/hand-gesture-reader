from handsign.temporal import HoldSpec, HoldTracker, PoseStabilizer

FRAME = 1 / 30


def feed(stabilizer, poses, start=0.0):
    out = []
    for i, pose in enumerate(poses):
        out.append(stabilizer.update(pose, start + i * FRAME))
    return out


def test_stable_after_half_window():
    results = feed(PoseStabilizer(300, 0.7), ["peace"] * 10)
    names = [name for name, _ in results]
    assert names[0] == "none"
    assert names[-1] == "peace"
    assert names.index("peace") == 5  # 150 ms of history at 30 fps


def test_flicker_is_tolerated():
    poses = ["peace"] * 9 + ["none"] + ["peace"] * 5
    results = feed(PoseStabilizer(300, 0.7), poses)
    since = {s for name, s in results if name == "peace"}
    assert results[-1][0] == "peace"
    assert len(since) == 1  # never dropped out


def test_mixed_poses_are_not_stable():
    results = feed(PoseStabilizer(300, 0.7), ["peace", "point"] * 10)
    assert {name for name, _ in results} == {"none"}


def test_hold_fires_once():
    tracker = HoldTracker(HoldSpec(400))
    events = [tracker.update("peace", 0.0, i * FRAME) for i in range(60)]
    fired = [e for e in events if e]
    assert len(fired) == 1 and not fired[0].repeat
    assert events.index(fired[0]) == 12  # first frame at >= 400 ms


def test_hold_repeats():
    tracker = HoldTracker(HoldSpec(400), {"thumbs_up": HoldSpec(200, repeat_ms=250)})
    events = [tracker.update("thumbs_up", 0.0, i * FRAME) for i in range(31)]  # 1 s
    fired = [e for e in events if e]
    assert [e.repeat for e in fired] == [False, True, True, True]


def test_hold_restarts_after_release():
    tracker = HoldTracker(HoldSpec(100))
    assert tracker.update("fist", 0.0, 0.2)
    assert tracker.update("fist", 0.0, 0.3) is None
    assert tracker.update("none", 0.4, 0.4) is None
    assert tracker.update("fist", 0.5, 0.55) is None
    assert tracker.update("fist", 0.5, 0.65)
