# AGENTS.md

This file provides guidance to AI coding agents working with code in this repository.

`handsign` reads hand signs from a webcam (MediaPipe hand landmarks) and turns them into actions:
shell commands, Hyprland dispatchers or synthetic key presses. Python ≥3.12, managed with uv.
README.md is the user-facing reference for gestures, config options and platform setup.

## Commands

```sh
uv sync                                   # install deps into .venv
uv run pytest                             # all tests (no camera needed)
uv run pytest tests/test_recognizer.py::test_repeat_binding   # single test
uv run ruff check . && uv run ruff format .
uv run handsign check                     # validate the config and list bindings
uv run handsign run --preview [--dry-run] # debug window; --dry-run dispatches no actions
uv run handsign detect IMAGE…             # run the classifier on still images
uv tool install --reinstall .             # refresh the installed ~/.local/bin/handsign (run by the service)
handsign service install|status|restart|logs|stop   # background service: systemd / launchd
```

Only one instance can run (it owns the camera and the control socket); `handsign service stop`
before running `handsign run` by hand, `handsign service restart` after reinstalling.

## Architecture

Pipeline: `camera → landmarks → poses → temporal/motion → recognizer (arming) → dispatcher → actions`.

- **Vision boundary**: `camera.py` (OpenCV capture) and `landmarks.py` (MediaPipe
  HandLandmarker, model downloaded to the cache dir on first use) are the only modules that
  touch frames. They produce `types.Hand`: 21 image landmarks (units of image height, mirrored
  as the user sees them) plus metric world landmarks, and the user's actual handedness.
- **Everything after that is pure geometry and camera-free**, which is what the tests cover:
  - `poses.py`: rule-based classifier. Finger extension / thumb state are ratios on world
    landmarks normalised by hand size; `_RULES` is ordered, first match wins. Thresholds live
    in `PoseThresholds` and are user-configurable under `[recognition.thresholds]`.
  - `temporal.py`: `PoseStabilizer` (sliding-window majority vote) and `HoldTracker`
    (fire after hold_ms, optionally repeat).
  - `motion.py`: `SwipeDetector` on palm centre in hand-size units; its speed also suppresses
    static poses while the hand moves.
  - `recognizer.py`: ties these together per frame, owns the arming state machine (open palm
    arms, fist disarms, timeout renewed by every fired gesture), and returns a `FrameState`
    used by the preview and `--record`. Hold specs are rebuilt when arming changes, because
    the arming pose has its own hold time only while disarmed.
- `dispatcher.py`: resolves a `GestureEvent` to a `Binding` — `GestureEvent.candidates` gives
  `"<pose>+<swipe>"` before `"<swipe>"`, and a hand-specific binding beats a generic one —
  applies per-binding cooldown, and runs the action on a thread pool so actions never block
  the vision loop.
- `engine.py`: the daemon loop — pause/resume (pause closes the camera), idle throttling to a
  low fps when no hand is seen, preview and JSONL recording. `control.py` is the `handsign ctl`
  channel: JSON lines over a unix socket in `$XDG_RUNTIME_DIR`, or `~/Library/Caches/handsign`
  on macOS (not `$TMPDIR`, which differs between launchd and a terminal); TCP localhost on
  Windows.
- `actions/`: each type registers a factory with `@register("<type>")` in `base.py`; importing
  the `actions` package registers all of them. `hyprland` subclasses `CommandAction` (runs
  `hyprctl dispatch`, finding the instance signature itself under systemd). `keys` uses a
  uinput virtual keyboard via evdev on Linux, pynput elsewhere (a platform-marker dependency;
  on macOS `open()` checks Accessibility access, without which key events are dropped silently).
- `service.py`: `handsign service …`. Linux: renders a systemd user unit and drives
  `systemctl --user`. macOS: a LaunchAgent that starts `~/Applications/Handsign.app`, an
  `osacompile` AppleScript applet running `handsign run` in a shell restart loop. The app exists
  for TCC: a bare executable started by launchd is silently denied the camera, whereas a child
  of an app is judged as the app, whose Info.plist carries `NSCameraUsageDescription`. Its
  output must be redirected to the log, since `do shell script` buffers it otherwise.
- `config.py`: TOML → frozen dataclasses. `_section()` validates keys and types generically
  against the dataclass defaults, so adding a field to a config dataclass is enough to make it
  configurable. Unknown keys are errors everywhere.

## Conventions and gotchas

- Tests build synthetic hands with `conftest.make_hand(fingers="IM", thumb="out", pinch=…,
  rotate_deg=…)` and drive `Recognizer.process(hands, t)` with explicit timestamps; all timing
  in the code is wall-clock (`t` in seconds), never frame counts.
- `handsign init` writes `default_config.toml` (options; its comments document every option)
  followed by `default_bindings_linux.toml` or `default_bindings_macos.toml` (Linux file for
  every non-macOS platform), joined in `config.default_config_text()`. Both bindings files must
  stay valid on their platform; `test_default_config_is_valid` parses each. When adding a
  pose, action type or config option, update them and the README tables too.
  Pose names come from `poses.POSES`, swipe names from `config.SWIPES`.
- Hyprland on this machine is 0.55+ (Lua config): dispatch strings are Lua expressions like
  `hl.dsp.focus({ workspace = "e+1" })`, not the legacy `workspace e+1` syntax.
- The dev machine is Linux, so the macOS service code is never run here: keep file rendering
  pure and all commands going through the injected runner (`tests/test_service.py` fakes it
  and `Path.home()`). Re-signing Handsign.app resets its camera / Accessibility grants, which is
  why `install` only rebuilds it when missing, when the executable path changes, or with
  `--force`.
- Ruff: line length 100, rules E/F/I/B/UP; B008 and B905 are intentionally ignored.
