import tomllib

import pytest

from handsign.actions import keys
from handsign.config import ConfigError, default_config_text, load_config, parse_config


class FakeKeys:
    def __init__(self):
        self.taps = []

    def validate(self, combo):
        if "bogus" in combo:
            raise keys.ActionError("unknown key 'bogus'")

    def tap(self, combo):
        self.taps.append(combo)


@pytest.fixture(autouse=True)
def fake_keys():
    backend = FakeKeys()
    keys.set_backend(backend)
    yield backend
    keys.set_backend(None)


def parse(text: str):
    return parse_config(tomllib.loads(text))


def test_default_config_is_valid(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    cfg = parse(default_config_text())
    assert cfg.arming.enabled and cfg.arming.pose == "open_palm"
    assert {b.gesture for b in cfg.bindings} >= {"thumbs_up", "peace", "open_palm+swipe_left"}


def test_empty_config_gives_defaults():
    cfg = parse("")
    assert cfg.camera.width == 640 and cfg.bindings == ()


def test_overrides_and_int_to_float():
    cfg = parse("""
        [camera]
        device = "/dev/video2"
        [recognition]
        hold_ms = 250
        [recognition.thresholds]
        finger_reach = 1.4
    """)
    assert cfg.camera.device == "/dev/video2"
    assert cfg.recognition.hold_ms == 250.0
    assert cfg.recognition.thresholds.finger_reach == 1.4


def test_binding_options():
    cfg = parse("""
        [[binding]]
        gesture = "point+swipe_right"
        hand = "left"
        cooldown_ms = 1000
        action = { type = "keys", combo = "Alt+Right" }
    """)
    (binding,) = cfg.bindings
    assert binding.hand == "left" and binding.cooldown_ms == 1000.0
    assert binding.action.combos == [["alt", "right"]]


@pytest.mark.parametrize(
    "text, message",
    [
        ("[camera]\nwidht = 3", "unknown keys"),
        ("[camera]\nwidth = 'big'", "expected int"),
        ("[arming]\npose = 'wave'", "not a known pose"),
        ("nonsense = 1", "unknown top-level"),
        ("[[binding]]\ngesture = 'wave'\naction = {type='command', argv=['true']}", "expected a pose"),
        ("[[binding]]\ngesture = 'swipe_left+peace'\naction = {type='command', argv=['true']}", "expected a pose"),
        ("[[binding]]\ngesture = 'peace'", "missing 'action'"),
        ("[[binding]]\ngesture = 'peace'\naction = {type='teleport'}", "unknown action type"),
        ("[[binding]]\ngesture = 'peace'\naction = {type='command'}", "exactly one of"),
        ("[[binding]]\ngesture = 'peace'\naction = {type='command', argv='ls'}", "list of strings"),
        ("[[binding]]\ngesture = 'peace'\naction = {type='keys', combo='ctrl+bogus'}", "unknown key"),
        ("[[binding]]\ngesture = 'peace'\naction = {type='keys', combo='ctrl++'}", "invalid key combo"),
        ("[[binding]]\ngesture = 'peace'\nhand = 'both'\naction = {type='command', argv=['true']}", "hand must be"),
        ("[[binding]]\ngesture = 'swipe_up'\nrepeat_ms = 5\naction = {type='command', argv=['true']}", "only apply to static"),
    ],
)  # fmt: skip
def test_errors(text, message):
    with pytest.raises(ConfigError, match=message):
        parse(text)


def test_hyprland_unsupported_without_hyprctl(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ConfigError, match="hyprctl not found"):
        parse("[[binding]]\ngesture='peace'\naction={type='hyprland', dispatch='workspace 1'}")


def test_load_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.toml")


def test_load_syntax_error(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[camera\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_command_detach(tmp_path):
    import time

    marker = tmp_path / "done"
    cfg = parse(f"""
        [[binding]]
        gesture = "three"
        action = {{ type = "command", shell = "sleep 0.3; touch {marker}", detach = true }}
    """)
    started = time.monotonic()
    cfg.bindings[0].action.run()
    assert time.monotonic() - started < 0.2  # did not wait
    deadline = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists()


def test_command_detach_must_be_bool():
    with pytest.raises(ConfigError, match="detach"):
        parse("[[binding]]\ngesture='three'\naction={type='command', argv=['true'], detach='yes'}")
