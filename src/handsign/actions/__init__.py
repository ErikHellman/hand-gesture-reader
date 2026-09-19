"""Action backends. Importing this package registers all built-in action types."""

from . import command, hyprland, keys  # noqa: F401  (registration side effects)
from .base import Action, ActionError, build_action

__all__ = ["Action", "ActionError", "build_action"]
