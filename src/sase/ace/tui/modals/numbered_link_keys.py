"""One-shot ``.`` + digit numbered-link dispatch for Glossary and Memory.

Bare ``1``-``9`` stay available to the Admin Center's top-level tabs. These
panes arm ``full_stop``, then resolve the next decimal digit on the
UI thread. The path is state-only: no I/O, workers, or pane rebuilds.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.events import Key
from textual.widgets import Input

NUMBERED_LINK_PREFIX_KEY = "full_stop"
NUMBERED_LINK_CHIP_PREFIX = "."
NUMBERED_LINK_MIN = 1
NUMBERED_LINK_MAX = 9
NUMBERED_LINK_HELP_KEYS = f"{NUMBERED_LINK_CHIP_PREFIX}1-{NUMBERED_LINK_MAX}"
NUMBERED_LINK_BINDING: tuple[str, str, str] = (
    NUMBERED_LINK_PREFIX_KEY,
    "arm_numbered_link",
    "Follow numbered link",
)


def _filter_has_focus(widget: Any) -> bool:
    focused = getattr(getattr(widget, "app", None), "focused", None)
    return isinstance(focused, Input)


def _is_prefix_key(event: Key) -> bool:
    character = getattr(event, "character", None)
    return event.key in (NUMBERED_LINK_PREFIX_KEY, ".") or character == "."


def _decimal_digit(event: Key) -> str | None:
    character = getattr(event, "character", None)
    selected_digit = (
        character if isinstance(character, str) and character.isdecimal() else event.key
    )
    if isinstance(selected_digit, str) and selected_digit.isdecimal():
        return selected_digit
    return None


def arm_numbered_link(widget: Any) -> None:
    """Arm one-shot numbered-link selection unless a filter Input has focus."""
    if _filter_has_focus(widget):
        return
    widget._pending_numbered_link = True


def clear_numbered_link_prefix(widget: Any) -> None:
    """Drop any armed numbered-link prefix without consuming a key."""
    widget._pending_numbered_link = False


def handle_numbered_link_key(
    widget: Any,
    event: Key,
    *,
    follow: Callable[[int], None],
) -> bool:
    """Resolve an armed ``.N`` numbered-link shortcut.

    Config-hub sub-tab forwarding must run first so an already-armed
    Config ``0`` prefix still wins. A repeated ``.`` stays armed. A digit
    outside ``1``-``9`` is consumed and cancels. Any other key cancels and
    continues through normal dispatch. Returns True when the event was
    consumed.
    """
    if _filter_has_focus(widget):
        widget._pending_numbered_link = False
        return False

    if _is_prefix_key(event):
        widget._pending_numbered_link = True
        event.prevent_default()
        event.stop()
        return True

    if not getattr(widget, "_pending_numbered_link", False):
        return False

    digit = _decimal_digit(event)
    if digit is not None:
        event.prevent_default()
        event.stop()
        widget._pending_numbered_link = False
        number = int(digit)
        if NUMBERED_LINK_MIN <= number <= NUMBERED_LINK_MAX:
            follow(number)
        return True

    widget._pending_numbered_link = False
    return False


__all__ = [
    "NUMBERED_LINK_BINDING",
    "NUMBERED_LINK_CHIP_PREFIX",
    "NUMBERED_LINK_HELP_KEYS",
    "NUMBERED_LINK_MAX",
    "NUMBERED_LINK_MIN",
    "NUMBERED_LINK_PREFIX_KEY",
    "arm_numbered_link",
    "clear_numbered_link_prefix",
    "handle_numbered_link_key",
]
