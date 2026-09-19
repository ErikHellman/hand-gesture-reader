"""User feedback through desktop notifications."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._notify_send = shutil.which("notify-send")

    def notify(self, message: str) -> None:
        log.info("%s", message)
        if not self.enabled:
            return
        if self._notify_send:
            argv = [
                self._notify_send, "--app-name=handsign", "--expire-time=1200",
                "--transient",
                # Replace the previous handsign notification instead of stacking.
                "--hint=string:x-canonical-private-synchronous:handsign",
                "handsign", message,
            ]  # fmt: skip
        elif sys.platform == "darwin":
            script = f'display notification "{message}" with title "handsign"'
            argv = ["osascript", "-e", script]
        else:
            return
        try:
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)  # fmt: skip
        except OSError as err:
            log.debug("notification failed: %s", err)
