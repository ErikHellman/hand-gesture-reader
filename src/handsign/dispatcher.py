"""Maps gesture events to bindings and runs their actions off the vision thread."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

from .config import Binding
from .types import GestureEvent

log = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, bindings: Iterable[Binding], *, workers: int = 4) -> None:
        self.bindings = tuple(bindings)
        self._last_fired: dict[int, float] = {}
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="action")

    def find(self, event: GestureEvent) -> Binding | None:
        for name in event.candidates:
            matches = [
                b for b in self.bindings if b.gesture == name and b.hand in (None, event.hand)
            ]
            if matches:
                # Prefer a hand-specific binding over a generic one.
                return max(matches, key=lambda b: b.hand is not None)
        return None

    def dispatch(self, event: GestureEvent, t: float) -> Binding | None:
        """Run the action bound to `event`. Returns the binding that fired, if any."""
        binding = self.find(event)
        if binding is None:
            return None
        if not event.repeat:
            last = self._last_fired.get(id(binding))
            if last is not None and (t - last) * 1000.0 < binding.cooldown_ms:
                log.debug("%s: in cooldown", binding.gesture)
                return None
        self._last_fired[id(binding)] = t
        log.info("%s (%s hand) -> %s", binding.gesture, event.hand, binding.action.describe())
        self._pool.submit(self._run, binding)
        return binding

    @staticmethod
    def _run(binding: Binding) -> None:
        try:
            binding.action.run()
        except Exception:
            log.exception("action for %s failed", binding.gesture)

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)
