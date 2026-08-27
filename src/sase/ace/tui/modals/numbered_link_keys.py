"""One-shot ``.`` + digit numbered-link dispatch for Glossary and Memory.

Bare ``1``-``9`` stay available to the Admin Center's top-level tabs. These
panes arm ``full_stop``, then resolve the next decimal digit on the
UI thread. The path is state-only: no I/O, workers, or pane rebuilds.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from textual.events import Key
from textual.widgets import Input

NUMBERED_LINK_MIN = 1
NUMBERED_LINK_MAX = 9


@dataclass(frozen=True, slots=True)
class _NumberedLinkPrefix:
    """Runtime state descriptor for one one-shot numbered-link prefix."""

    prefix_key: str
    chip_prefix: str
    state_attr: str


NUMBERED_LINK_PREFIX = _NumberedLinkPrefix(
    "full_stop",
    ".",
    "_pending_numbered_link",
)
LINK_FOLLOW_PREFIX = _NumberedLinkPrefix(
    "dollar_sign",
    "$",
    "_pending_link_prefix",
)
NUMBERED_LINK_PREFIX_KEY = NUMBERED_LINK_PREFIX.prefix_key
NUMBERED_LINK_CHIP_PREFIX = NUMBERED_LINK_PREFIX.chip_prefix
NUMBERED_LINK_HELP_KEYS = f"{NUMBERED_LINK_CHIP_PREFIX}1-{NUMBERED_LINK_MAX}"
NUMBERED_LINK_BINDING: tuple[str, str, str] = (
    NUMBERED_LINK_PREFIX_KEY,
    "arm_numbered_link",
    "Follow numbered link",
)


def _filter_has_focus(widget: Any) -> bool:
    focused = getattr(getattr(widget, "app", None), "focused", None)
    return isinstance(focused, Input)


def _is_prefix_key(event: Key, prefix: _NumberedLinkPrefix) -> bool:
    character = getattr(event, "character", None)
    return (
        event.key in (prefix.prefix_key, prefix.chip_prefix)
        or character == prefix.chip_prefix
    )


def _decimal_digit(event: Key) -> str | None:
    character = getattr(event, "character", None)
    selected_digit = (
        character if isinstance(character, str) and character.isdecimal() else event.key
    )
    if isinstance(selected_digit, str) and selected_digit.isdecimal():
        return selected_digit
    return None


def arm_link_prefix(widget: Any, prefix: _NumberedLinkPrefix) -> None:
    """Arm one-shot numbered-link selection unless a filter Input has focus."""
    if _filter_has_focus(widget):
        return
    setattr(widget, prefix.state_attr, True)


def clear_link_prefix(widget: Any, prefix: _NumberedLinkPrefix) -> None:
    """Drop any armed numbered-link prefix without consuming a key."""
    setattr(widget, prefix.state_attr, False)


def handle_link_prefix_key(
    widget: Any,
    event: Key,
    prefix: _NumberedLinkPrefix,
    *,
    follow: Callable[[int], None],
    on_double: Callable[[], None] | None = None,
    on_zero: Callable[[], None] | None = None,
) -> bool:
    """Resolve an armed numbered-link shortcut.

    Config-hub sub-tab forwarding must run first so an already-armed
    Config ``0`` prefix still wins. A repeated prefix stays armed unless
    *on_double* handles it. A digit outside ``1``-``9`` is consumed and
    cancels unless *on_zero* handles ``0``. Any other key cancels and
    continues through normal dispatch. Returns True when the event was consumed.
    """
    if _filter_has_focus(widget):
        setattr(widget, prefix.state_attr, False)
        return False

    if _is_prefix_key(event, prefix):
        if getattr(widget, prefix.state_attr, False) and on_double is not None:
            setattr(widget, prefix.state_attr, False)
            on_double()
        else:
            setattr(widget, prefix.state_attr, True)
        event.prevent_default()
        event.stop()
        return True

    if not getattr(widget, prefix.state_attr, False):
        return False

    digit = _decimal_digit(event)
    if digit is not None:
        event.prevent_default()
        event.stop()
        setattr(widget, prefix.state_attr, False)
        number = int(digit)
        if number == 0 and on_zero is not None:
            on_zero()
        elif NUMBERED_LINK_MIN <= number <= NUMBERED_LINK_MAX:
            follow(number)
        return True

    setattr(widget, prefix.state_attr, False)
    return False


def arm_numbered_link(widget: Any) -> None:
    """Arm the legacy ``.`` numbered-link selector."""
    arm_link_prefix(widget, NUMBERED_LINK_PREFIX)


def clear_numbered_link_prefix(widget: Any) -> None:
    """Drop any armed legacy ``.`` numbered-link prefix."""
    clear_link_prefix(widget, NUMBERED_LINK_PREFIX)


def handle_numbered_link_key(
    widget: Any,
    event: Key,
    *,
    follow: Callable[[int], None],
) -> bool:
    """Resolve an armed legacy ``.N`` numbered-link shortcut."""
    return handle_link_prefix_key(
        widget,
        event,
        NUMBERED_LINK_PREFIX,
        follow=follow,
    )


__all__ = [
    "LINK_FOLLOW_PREFIX",
    "NUMBERED_LINK_BINDING",
    "NUMBERED_LINK_CHIP_PREFIX",
    "NUMBERED_LINK_HELP_KEYS",
    "NUMBERED_LINK_MAX",
    "NUMBERED_LINK_MIN",
    "NUMBERED_LINK_PREFIX",
    "NUMBERED_LINK_PREFIX_KEY",
    "arm_link_prefix",
    "arm_numbered_link",
    "clear_link_prefix",
    "clear_numbered_link_prefix",
    "handle_link_prefix_key",
    "handle_numbered_link_key",
]
