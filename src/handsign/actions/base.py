"""Action protocol and registry. An action is built from the `action = {...}` table of a binding."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class ActionError(ValueError):
    """Invalid action definition or unsupported on this platform."""


class Action(Protocol):
    def run(self) -> None: ...

    def describe(self) -> str: ...


_REGISTRY: dict[str, Callable[[dict[str, Any]], Action]] = {}


def register(kind: str) -> Callable[[Callable[[dict[str, Any]], Action]], Callable]:
    def decorator(factory: Callable[[dict[str, Any]], Action]) -> Callable:
        _REGISTRY[kind] = factory
        return factory

    return decorator


def build_action(spec: dict[str, Any]) -> Action:
    if not isinstance(spec, dict) or "type" not in spec:
        raise ActionError("action must be a table with a 'type' key")
    spec = dict(spec)
    kind = spec.pop("type")
    try:
        factory = _REGISTRY[kind]
    except KeyError:
        raise ActionError(
            f"unknown action type {kind!r} (expected one of {sorted(_REGISTRY)})"
        ) from None
    return factory(spec)


def check_keys(spec: dict[str, Any], allowed: set[str], kind: str) -> None:
    unknown = set(spec) - allowed
    if unknown:
        raise ActionError(f"{kind} action: unknown keys {sorted(unknown)}")
