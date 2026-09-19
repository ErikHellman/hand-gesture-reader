"""Run handsign as a per-user background service: `handsign service install` and friends.

Linux: a systemd user unit.

macOS: a launchd LaunchAgent that starts a small wrapper app, ~/Applications/Handsign.app.
The app is what lets macOS grant camera access at all: TCC judges a process started by
launchd on its own and silently denies the camera to a bare executable, while a child of an
app is judged as that app (just as anything started from a terminal uses the terminal's
permissions). The app is an AppleScript applet, as `osacompile` ships with every Mac, whose
Info.plist carries the camera usage description. It runs handsign in a restart loop and stays
alive while handsign runs. Re-signing the app resets its permissions, so it is only rebuilt
when needed.

Rendering the files is pure and commands go through a runner, so the tests need neither
systemd nor macOS.
"""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol

ACTIONS = ("install", "uninstall", "start", "stop", "restart", "status", "logs")
UNIT = "handsign"
LABEL = "io.hellman.handsign"
RESTART_DELAY_S = 5


class ServiceError(RuntimeError):
    pass


class Runner(Protocol):
    def __call__(self, argv: list[str], *, quiet: bool = False) -> int: ...


def run_command(argv: list[str], *, quiet: bool = False) -> int:
    out = subprocess.DEVNULL if quiet else None
    try:
        return subprocess.call(argv, stdout=out, stderr=out)
    except FileNotFoundError as err:
        raise ServiceError(f"{argv[0]} not found") from err


def executable() -> Path:
    """The handsign executable for the service: the one on PATH, else the running one.

    Symlinks are kept, so ~/.local/bin/handsign stays valid across `uv tool install`s."""
    found = shutil.which("handsign")
    path = Path(found or sys.argv[0]).absolute()
    if not path.is_file():
        raise ServiceError(f"cannot find the handsign executable ({path}): uv tool install .")
    if ".venv" in path.parts:
        print(
            f"warning: the service will run {path} from a development environment; "
            "`uv tool install .` installs a stable one",
            file=sys.stderr,
        )
    return path


def get_service(runner: Runner = run_command) -> SystemdService | LaunchdService:
    if sys.platform.startswith("linux"):
        return SystemdService(runner)
    if sys.platform == "darwin":
        return LaunchdService(runner)
    raise ServiceError(f"no service support on {sys.platform}: start `handsign run` at login")


def _call(runner: Runner, argv: list[str]) -> None:
    if runner(argv) != 0:
        raise ServiceError(f"`{shlex.join(argv)}` failed")


# -- Linux: systemd user unit -------------------------------------------------------------

_UNIT_TEMPLATE = """\
[Unit]
Description=handsign - control the computer with hand signs
PartOf=graphical-session.target
After=graphical-session.target

[Service]
# Written by `handsign service install`.
ExecStart={exec_start} run
Restart=on-failure
RestartSec={delay}

[Install]
WantedBy=graphical-session.target
"""


def systemd_unit(exe: Path, home: Path | None = None) -> str:
    home = home or Path.home()
    if exe.is_relative_to(home):
        path = "%h/" + str(exe.relative_to(home)).replace("%", "%%")
    else:
        path = str(exe).replace("%", "%%")
    if any(c.isspace() or c in "\"'\\" for c in path):
        path = '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return _UNIT_TEMPLATE.format(exec_start=path, delay=RESTART_DELAY_S)


class SystemdService:
    def __init__(self, runner: Runner = run_command) -> None:
        self._run = runner

    @property
    def unit_path(self) -> Path:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        return base / "systemd" / "user" / f"{UNIT}.service"

    def _systemctl(self, *args: str) -> None:
        _call(self._run, ["systemctl", "--user", *args])

    def install(self, *, start: bool = True, force: bool = False) -> None:
        path = self.unit_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(systemd_unit(executable()), encoding="utf-8")
        print(f"wrote {path}")
        self._systemctl("daemon-reload")
        self._systemctl("enable", UNIT)
        if start:
            self._systemctl("restart", UNIT)  # picks up a changed unit or executable

    def uninstall(self) -> None:
        self._run(["systemctl", "--user", "disable", "--now", UNIT])
        self.unit_path.unlink(missing_ok=True)
        self._systemctl("daemon-reload")
        print(f"removed {self.unit_path}")

    def start(self) -> None:
        self._systemctl("start", UNIT)

    def stop(self) -> None:
        self._systemctl("stop", UNIT)

    def restart(self) -> None:
        self._systemctl("restart", UNIT)

    def status(self) -> int:
        return self._run(["systemctl", "--user", "--no-pager", "status", UNIT])

    def logs(self) -> int:
        return self._run(["journalctl", "--user", "-u", UNIT, "-f"])


# -- macOS: LaunchAgent + wrapper app -----------------------------------------------------


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def applet_source(exe: Path, log: Path) -> str:
    # launchd's PATH is minimal; commands in bindings expect the usual places.
    script = (
        'export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"; '
        # Output must go to the log: `do shell script` would collect it in memory forever.
        f"while :; do {shlex.quote(str(exe))} run >>{shlex.quote(str(log))} 2>&1 && break; "
        f"sleep {RESTART_DELAY_S}; done"
    )
    return (
        "-- Written by `handsign service install`: run handsign until it exits cleanly.\n"
        "try\n"
        f"\tdo shell script {_applescript_string(script)}\n"
        "end try\n"
    )


def patch_info_plist(info: dict, exe: Path) -> dict:
    return {
        **info,
        "CFBundleIdentifier": LABEL,
        "CFBundleName": "Handsign",
        "LSUIElement": True,  # no Dock icon
        "NSCameraUsageDescription": "handsign reads hand signs from the camera.",
        "HandsignExecutable": str(exe),  # rebuild when this changes
    }


def launchd_plist(program: Path, log: Path) -> bytes:
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [str(program)],
            "RunAtLoad": True,
            "ProcessType": "Interactive",
            "LimitLoadToSessionType": "Aqua",
            "StandardOutPath": str(log),
            "StandardErrorPath": str(log),
        }
    )


class LaunchdService:
    def __init__(self, runner: Runner = run_command) -> None:
        self._run = runner
        home = Path.home()
        self.app = home / "Applications" / "Handsign.app"
        self.plist = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        self.log = home / "Library" / "Logs" / "handsign.log"
        self._domain = f"gui/{os.getuid()}"
        self._target = f"{self._domain}/{LABEL}"

    def _info(self) -> dict:
        try:
            return plistlib.loads((self.app / "Contents" / "Info.plist").read_bytes())
        except (OSError, plistlib.InvalidFileException):
            return {}

    def _build_app(self, exe: Path) -> None:
        if self.app.exists():
            shutil.rmtree(self.app)
        self.app.parent.mkdir(parents=True, exist_ok=True)
        argv = ["osacompile", "-o", str(self.app)]
        for line in applet_source(exe, self.log).splitlines():
            argv += ["-e", line]
        _call(self._run, argv)
        info_path = self.app / "Contents" / "Info.plist"
        info_path.write_bytes(plistlib.dumps(patch_info_plist(self._info(), exe)))
        # Editing Info.plist broke the signature; an ad-hoc one is enough for TCC.
        _call(self._run, ["codesign", "--force", "--sign", "-", str(self.app)])
        print(f"built {self.app}: allow it to use the camera when macOS asks")

    def _loaded(self) -> bool:
        return self._run(["launchctl", "print", self._target], quiet=True) == 0

    def _bootstrap(self) -> None:
        if not self.plist.exists():
            raise ServiceError("not installed: run `handsign service install`")
        _call(self._run, ["launchctl", "bootstrap", self._domain, str(self.plist)])

    def install(self, *, start: bool = True, force: bool = False) -> None:
        exe = executable()
        if force or self._info().get("HandsignExecutable") != str(exe):
            self._build_app(exe)
        else:
            print(f"keeping {self.app} and its permissions (--force rebuilds it)")
        program = self.app / "Contents" / "MacOS" / self._info().get("CFBundleExecutable", "applet")
        self.plist.parent.mkdir(parents=True, exist_ok=True)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.plist.write_bytes(launchd_plist(program, self.log))
        print(f"wrote {self.plist}")
        if start:
            self._run(["launchctl", "bootout", self._target], quiet=True)
            self._bootstrap()

    def uninstall(self) -> None:
        self._run(["launchctl", "bootout", self._target], quiet=True)
        self.plist.unlink(missing_ok=True)
        if self.app.exists():
            shutil.rmtree(self.app)
        print(f"removed {self.plist} and {self.app}")
        print(f"to also forget its camera permission: tccutil reset Camera {LABEL}")

    def start(self) -> None:
        if self._loaded():
            _call(self._run, ["launchctl", "kickstart", self._target])
        else:
            self._bootstrap()

    def stop(self) -> None:
        # Unloads the agent; launchd ends the whole process group. It loads again at login.
        if self._loaded():
            _call(self._run, ["launchctl", "bootout", self._target])

    def restart(self) -> None:
        if self._loaded():
            _call(self._run, ["launchctl", "kickstart", "-k", self._target])
        else:
            self._bootstrap()

    def status(self) -> int:
        if not self._loaded():
            where = "starts at login" if self.plist.exists() else "not installed"
            print(f"{LABEL}: not loaded ({where})")
            return 3
        print(f"{LABEL}: loaded, log: {self.log}")
        return self._run(["launchctl", "list", LABEL])

    def logs(self) -> int:
        return self._run(["tail", "-n", "50", "-F", str(self.log)])
