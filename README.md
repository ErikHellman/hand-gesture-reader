# handsign

Reads hand signs from a webcam and turns them into actions on your computer: shell commands,
Hyprland dispatchers or synthetic key presses.

```
camera → MediaPipe hand landmarks → pose rules ─┬→ vote / hold / repeat ─┐
                                                └→ swipe detector ───────┴→ arming → bindings → actions
```

Everything after the landmark model is plain geometry on 21 points, so there is nothing to
train and the recognition logic is tested without a camera.

## Install

Needs [uv](https://docs.astral.sh/uv/). The hand-landmark model (8 MB) is downloaded to the
cache directory on first run.

```sh
uv sync                                  # development: run with `uv run handsign …`
uv tool install .                        # or install `handsign` into ~/.local/bin
                                         # (after code changes: uv tool install --reinstall .)
handsign init                            # writes ~/.config/handsign/config.toml
handsign run --preview                   # debug window: landmarks, pose, armed state, events
```

## Using it

1. Hold an **open palm** towards the camera for 0.6 s → *armed* (desktop notification).
2. Make a gesture. Each gesture keeps it armed for another 5 s; a **fist** disarms.

Set `arming.enabled = false` to react to gestures at all times.

| Poses | |
|---|---|
| `open_palm` `four` `three` `peace` `point` `fist` | fingers up; `four` = thumb folded across the palm |
| `thumbs_up` `thumbs_down` | only the thumb out, pointing up / down |
| `rock` `call` | index + pinky / thumb + pinky |
| `ok` `pinch` | thumb and index tip together, other fingers extended / curled |

A pose fires once after being held still for 0.4 s (`recognition.hold_ms`); poses are ignored
while the hand is moving fast. A thumb pointing sideways is neither `thumbs_up` nor `thumbs_down`.

Swipes: `swipe_left` `swipe_right` `swipe_up` `swipe_down`, as you see them. Bind
`open_palm+swipe_left` to require a pose during the swipe; the most specific binding wins.

Default bindings: thumbs up / down = volume (repeats while held), peace = play/pause,
rock = mute, point + swipe = next / previous track, open palm + swipe = Hyprland workspace.

```toml
[[binding]]
gesture = "three"
hand = "right"            # optional
repeat_ms = 300           # optional: fire again while held
action = { type = "keys", combo = "ctrl+alt+Right" }
```

Action types:

- `command`: `argv = [...]` or `shell = "..."`. Commands are waited for and killed after 15 s;
  add `detach = true` to launch an application instead.
- `hyprland`: `dispatch = ...`, see the platform notes for the syntax. Also the best way to
  start applications on Hyprland, because they then belong to the compositor rather than to
  the handsign service: `dispatch = 'hl.dsp.exec_cmd("ghostty")'`.
- `keys`: `combo = "..."` or `sequence = [...]`.

Per binding you can also set `hand`, `hold_ms`, `repeat_ms` and `cooldown_ms` (default 500).
`handsign check` validates the config and lists the bindings; the comments in the generated
config describe every option. The config is read at startup, so restart handsign after editing.

### Commands

```
handsign [-v] [-c CONFIG] <command>
handsign run [--preview] [--dry-run] [--record FILE]
handsign ctl status|pause|resume|toggle|quit     # pause releases the camera (LED off)
handsign init [--force] | check | cameras | detect IMAGE…
```

Only one instance can run at a time (it owns the camera and the control socket).

A Hyprland keybind to toggle the camera (full path, as the compositor's `PATH` may not include
`~/.local/bin`):
`hl.bind("SUPER + G", hl.dsp.exec_cmd("~/.local/bin/handsign ctl toggle"))`

### Run as a service

Expects the executable from `uv tool install .` in `~/.local/bin`.

```sh
mkdir -p ~/.config/systemd/user
cp systemd/handsign.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now handsign

systemctl --user restart handsign        # after editing the config or reinstalling
journalctl --user -u handsign -f         # logs
```

Stop the service before running `handsign run --preview` by hand.

## Tuning

Run with `--preview`. The overlay shows the per-frame pose, its confidence, the finger states
(`T I M R P`) and the stable pose. If a finger flips state, adjust `[recognition.thresholds]`
(explained in `src/handsign/poses.py`). `handsign run --record out.jsonl` dumps the landmarks
of a session for offline analysis.

Many webcams lower their frame rate in dim light (18 fps on the development laptop). All timing
is wall-clock based so this is fine, but for fast swipes more light helps, or:
`v4l2-ctl -c exposure_dynamic_framerate=0`.

## Platform notes

- **Linux**: key presses go through a virtual keyboard on `/dev/uinput`, which works on Wayland,
  X11 and the console. uinput sends key *codes*, so letters follow your keyboard layout. If
  `/dev/uinput` is not writable for your user:
  ```sh
  echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' \
    | sudo tee /etc/udev/rules.d/80-uinput.rules
  sudo usermod -aG input $USER    # then log in again
  ```
- **Hyprland 0.55+** (Lua) dispatchers are Lua expressions:
  `dispatch = 'hl.dsp.focus({ workspace = "e+1" })'`. Older versions: `dispatch = "workspace e+1"`.
  The running instance is found automatically when started from systemd.
- **macOS / Windows**: untested. `command` actions work as they are, `keys` needs
  `pip install 'handsign[desktop]'` (pynput), `hyprland` is rejected when the config is loaded.

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format .
```
