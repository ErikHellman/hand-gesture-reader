"""Run an external command."""

from __future__ import annotations

import logging
import shlex
import subprocess
from typing import Any

from .base import ActionError, check_keys, register

log = logging.getLogger(__name__)


class CommandAction:
    def __init__(
        self,
        argv: list[str] | str,
        *,
        shell: bool = False,
        env: dict[str, str] | None = None,
        detach: bool = False,
    ) -> None:
        self.argv = argv
        self.shell = shell
        self.env = env
        self.detach = detach
        self.timeout = 15.0

    def _spawn(self) -> None:
        """Start a long-running program (an application) without waiting for it."""
        try:
            subprocess.Popen(
                self.argv,
                shell=self.shell,
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError:
            log.error("command not found: %s", self.describe())

    def run(self) -> None:
        if self.detach:
            self._spawn()
            return
        try:
            result = subprocess.run(
                self.argv,
                shell=self.shell,
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,  # some tools (hyprctl) report errors on stdout
                stderr=subprocess.STDOUT,
                timeout=self.timeout,
                text=True,
            )
        except FileNotFoundError:
            log.error("command not found: %s", self.describe())
            return
        except subprocess.TimeoutExpired:
            log.error("command timed out: %s", self.describe())
            return
        if result.returncode != 0:
            log.warning(
                "command failed (%d): %s: %s",
                result.returncode,
                self.describe(),
                result.stdout.strip(),
            )

    def describe(self) -> str:
        return self.argv if isinstance(self.argv, str) else shlex.join(self.argv)


@register("command")
def _build(spec: dict[str, Any]) -> CommandAction:
    check_keys(spec, {"argv", "shell", "detach"}, "command")
    detach = spec.get("detach", False)
    if not isinstance(detach, bool):
        raise ActionError("command action: 'detach' must be true or false")
    if ("argv" in spec) == ("shell" in spec):
        raise ActionError("command action needs exactly one of 'argv' (list) or 'shell' (string)")
    if "argv" in spec:
        argv = spec["argv"]
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise ActionError("command action: 'argv' must be a non-empty list of strings")
        return CommandAction(argv, detach=detach)
    if not isinstance(spec["shell"], str) or not spec["shell"].strip():
        raise ActionError("command action: 'shell' must be a non-empty string")
    return CommandAction(spec["shell"], shell=True, detach=detach)
