import plistlib
from pathlib import Path

import pytest

from handsign import control, service


class FakeRunner:
    """Records commands; `osacompile` leaves a minimal applet bundle behind."""

    def __init__(self, loaded: bool = False):
        self.calls: list[list[str]] = []
        self.loaded = loaded

    def __call__(self, argv, *, quiet=False):
        self.calls.append(argv)
        if argv[0] == "osacompile":
            contents = Path(argv[argv.index("-o") + 1]) / "Contents"
            contents.mkdir(parents=True)
            info = {"CFBundleExecutable": "applet", "CFBundleName": "applet"}
            (contents / "Info.plist").write_bytes(plistlib.dumps(info))
        if argv[:2] == ["launchctl", "print"]:
            return 0 if self.loaded else 113
        return 0

    def commands(self):
        return [argv[:2] if argv[0] == "launchctl" else argv[:1] for argv in self.calls]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    exe = tmp_path / ".local" / "bin" / "handsign"
    exe.parent.mkdir(parents=True)
    exe.touch()
    monkeypatch.setattr("shutil.which", lambda name: str(exe))
    return tmp_path


def test_systemd_unit_uses_home_specifier():
    unit = service.systemd_unit(Path("/home/me/.local/bin/handsign"), home=Path("/home/me"))
    assert "ExecStart=%h/.local/bin/handsign run\n" in unit
    assert "Restart=on-failure" in unit


def test_systemd_unit_quotes_and_escapes():
    unit = service.systemd_unit(Path('/opt/my apps/50%/"hs"'), home=Path("/home/me"))
    assert 'ExecStart="/opt/my apps/50%%/\\"hs\\"" run\n' in unit


def test_systemd_install_and_uninstall(home):
    runner = FakeRunner()
    svc = service.SystemdService(runner)
    svc.install()
    unit = home / ".config" / "systemd" / "user" / "handsign.service"
    assert "ExecStart=%h/.local/bin/handsign run" in unit.read_text()
    assert runner.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "handsign"],
        ["systemctl", "--user", "restart", "handsign"],
    ]

    runner.calls.clear()
    svc.uninstall()
    assert not unit.exists()
    assert runner.calls[0] == ["systemctl", "--user", "disable", "--now", "handsign"]


def test_systemd_install_no_start(home):
    runner = FakeRunner()
    service.SystemdService(runner).install(start=False)
    assert ["systemctl", "--user", "restart", "handsign"] not in runner.calls


def test_failed_command_raises(home):
    svc = service.SystemdService(lambda argv, quiet=False: 1)
    with pytest.raises(service.ServiceError, match="daemon-reload"):
        svc.install()


def test_applet_source_escapes_paths():
    source = service.applet_source(Path("/Users/a b/it's\\\"x"), Path("/Users/a b/h.log"))
    line = source.splitlines()[2]
    assert line.startswith('\tdo shell script "') and line.endswith('"')
    # Undo the AppleScript string escaping to get the shell command back.
    script = line[len('\tdo shell script "') : -1].replace('\\"', '"').replace("\\\\", "\\")
    assert "'/Users/a b/it'\"'\"'s\\\"x' run >>'/Users/a b/h.log' 2>&1 && break" in script
    assert "sleep 5" in script


def test_launchd_plist():
    data = plistlib.loads(service.launchd_plist(Path("/A.app/Contents/MacOS/applet"), Path("/l")))
    assert data["Label"] == service.LABEL
    assert data["ProgramArguments"] == ["/A.app/Contents/MacOS/applet"]
    assert data["RunAtLoad"] is True
    assert data["StandardOutPath"] == data["StandardErrorPath"] == "/l"


def test_patch_info_plist():
    info = service.patch_info_plist({"CFBundleExecutable": "applet"}, Path("/x/handsign"))
    assert info["CFBundleExecutable"] == "applet"
    assert info["CFBundleIdentifier"] == service.LABEL
    assert info["LSUIElement"] is True
    assert info["NSCameraUsageDescription"]


def test_launchd_install(home):
    runner = FakeRunner()
    svc = service.LaunchdService(runner)
    svc.install()
    assert runner.commands() == [
        ["osacompile"],
        ["codesign"],
        ["launchctl", "bootout"],
        ["launchctl", "bootstrap"],
    ]
    info = plistlib.loads((svc.app / "Contents" / "Info.plist").read_bytes())
    assert info["NSCameraUsageDescription"]
    assert info["HandsignExecutable"] == str(home / ".local" / "bin" / "handsign")
    agent = plistlib.loads(svc.plist.read_bytes())
    assert agent["ProgramArguments"] == [str(svc.app / "Contents" / "MacOS" / "applet")]
    assert svc.plist == home / "Library" / "LaunchAgents" / "io.hellman.handsign.plist"

    # Reinstalling keeps the app (and so its camera permission) unless forced.
    runner.calls.clear()
    svc.install()
    assert ["osacompile"] not in runner.commands()
    svc.install(force=True, start=False)
    assert runner.commands()[-2:] == [["osacompile"], ["codesign"]]


def test_launchd_rebuilds_app_when_executable_moves(home, monkeypatch):
    runner = FakeRunner()
    svc = service.LaunchdService(runner)
    svc.install(start=False)
    other = home / "elsewhere" / "handsign"
    other.parent.mkdir()
    other.touch()
    monkeypatch.setattr("shutil.which", lambda name: str(other))
    runner.calls.clear()
    svc.install(start=False)
    assert runner.commands() == [["osacompile"], ["codesign"]]


def test_launchd_start_stop(home):
    runner = FakeRunner()
    svc = service.LaunchdService(runner)
    with pytest.raises(service.ServiceError, match="not installed"):
        svc.start()
    svc.install(start=False)
    runner.calls.clear()
    svc.start()
    assert runner.commands()[-1] == ["launchctl", "bootstrap"]
    runner.loaded = True
    svc.restart()
    assert runner.calls[-1][:3] == ["launchctl", "kickstart", "-k"]
    svc.stop()
    assert runner.commands()[-1] == ["launchctl", "bootout"]


def test_control_socket_on_macos(home, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr("sys.platform", "darwin")
    assert control.socket_path() == home / "Library" / "Caches" / "handsign" / "handsign.sock"
