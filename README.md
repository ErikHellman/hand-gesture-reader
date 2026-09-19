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
handsign init                            # writes the config file (bindings for your platform)
handsign run --preview                   # debug window: landmarks, pose, armed state, events
handsign service install                 # run in the background, started at login
```

The config lives in `~/.config/handsign/config.toml` on Linux and
`~/Library/Application Support/handsign/config.toml` on macOS. Linux and macOS use the same
install steps; everything platform-specific is covered in
[Run as a service](#run-as-a-service) and the [platform notes](#platform-notes).

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
rock = mute, point + swipe = next / previous track, open palm + swipe = previous / next
workspace. On Linux they use `wpctl`, `playerctl` and Hyprland. On macOS they use `osascript`
for the volume, media keys for playback, and ctrl+←/→ to switch Spaces.

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
handsign service install [--no-start] [--force] | uninstall | start | stop | restart | status | logs
handsign init [--force] | check | cameras | detect IMAGE…
```

Only one instance can run at a time (it owns the camera and the control socket).

A keybind to toggle the camera. Use the full path, since the `PATH` there may not include
`~/.local/bin`:

- Hyprland: `hl.bind("SUPER + G", hl.dsp.exec_cmd("~/.local/bin/handsign ctl toggle"))`
- macOS: create a Shortcuts shortcut with a *Run Shell Script* action running
  `~/.local/bin/handsign ctl toggle`, then give it a keyboard shortcut in its details.

### Run as a service

`handsign service` runs handsign in the background for your user. It starts at login and
restarts after a crash. It uses a systemd user unit on Linux and a launchd agent on macOS.
Install the executable with `uv tool install .` first. The service runs the `handsign` found on
`PATH` (normally `~/.local/bin/handsign`), so later `uv tool install --reinstall .` runs need
only a `handsign service restart`.

```sh
handsign service install     # write the service files, enable at login, start now
handsign service status      # service state plus the daemon's own status
handsign service logs        # follow the log
handsign service restart     # after editing the config or reinstalling handsign
handsign service stop        # stop until the next login (or `start`)
handsign service uninstall   # stop and remove the service files
```

Stop the service before running `handsign run --preview` by hand.

#### Linux (systemd)

`install` writes `~/.config/systemd/user/handsign.service` (`ExecStart=%h/.local/bin/handsign
run`, `Restart=on-failure`, bound to `graphical-session.target`), then runs
`systemctl --user daemon-reload`, `enable handsign` and `restart handsign`. The other actions
map to `systemctl --user` and `journalctl --user -u handsign -f`, which you can also use
directly.

The unit starts with `graphical-session.target`, which most desktop environments and Hyprland
under UWSM start. If yours doesn't (`systemctl --user is-active graphical-session.target`),
run `systemctl --user start handsign` from your compositor's autostart instead. `keys`
actions also need access to `/dev/uinput` (see the platform notes).

#### macOS (launchd)

macOS only lets a background process use the camera if it belongs to an app. A launchd job
that runs `~/.local/bin/handsign` directly is denied camera access, with no prompt and no
error. So `install` builds a small wrapper app and has launchd start that:

- `~/Applications/Handsign.app`: an AppleScript applet made with `osacompile`, with a camera
  usage description in its `Info.plist` and an ad-hoc signature. It runs `handsign run` and
  restarts it 5 s after a failure. It has no Dock icon.
- `~/Library/LaunchAgents/io.hellman.handsign.plist`: starts the app at login.
- `~/Library/Logs/handsign.log`: the log, also visible in Console.app.

First start:

1. macOS asks whether **Handsign** may use the camera: allow it. handsign's first attempt
   fails while the dialog is open; it retries by itself 5 s later.
2. For `keys` actions (the default media and Spaces bindings), enable **Handsign** under
   System Settings → Privacy & Security → **Accessibility**. handsign asks for this at startup
   and logs a warning while it is missing; without it, macOS silently drops the key presses.
   Run `handsign service restart` after enabling it.

Permissions belong to that particular build of the app. `install` rebuilds it only if it is
missing, if the handsign executable moved, or with `--force`; after a rebuild, allow the
camera again and re-enable Accessibility (remove the old entry first). `uninstall` deletes the
app and the agent but leaves the camera permission in place; to reset it too:
`tccutil reset Camera io.hellman.handsign`.

`stop` unloads the agent (`launchctl bootout`) and `start` / `restart` use
`launchctl bootstrap` / `kickstart`. The agent stays installed, so it starts again at the next
login until you `uninstall` it.

Commands in bindings run with `PATH` set to `~/.local/bin`, `/opt/homebrew/bin` and
`/usr/local/bin` followed by the system directories.

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
- **macOS**: see [Run as a service](#macos-launchd) for the camera and Accessibility
  permissions. When you run `handsign run` in a terminal, those permissions are the terminal
  app's instead. `keys` uses pynput (installed automatically), so it sends characters and
  media keys rather than key codes. The control socket is
  `~/Library/Caches/handsign/handsign.sock`. `hyprland` actions are rejected when the config
  is loaded.
- **Windows**: untested. `command` and `keys` actions should work; there is no
  `handsign service`, so start `handsign run` at login yourself.

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format .
```
