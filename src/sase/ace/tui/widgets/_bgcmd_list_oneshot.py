"""Oneshot helpers for the background command list widget.

The clock resolves through the ``bgcmd_list`` namespace (lazy import at
call time) so the ``get_timezone`` / ``local_now`` patch targets keep
resolving through ``bgcmd_list`` after the split.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from ._bgcmd_list_styles import (
    _ONESHOT_DONE_CHIP_STYLE,
    _ONESHOT_FAIL_CHIP_STYLE,
    _ONESHOT_FAIL_GLYPH,
    _ONESHOT_OK_CHIP_STYLE,
    _ONESHOT_OK_GLYPH,
    _ONESHOT_RUN_CHIP_STYLE,
    _ONESHOT_RUN_GLYPH,
)

if TYPE_CHECKING:
    from ..bgcmd import BackgroundCommandInfo


def oneshot_failed(info: "BackgroundCommandInfo | None") -> bool:
    if info is None:
        return False
    if info.status in {"error", "killed"}:
        return True
    return info.exit_code not in (None, 0)


def oneshot_glyph(
    info: "BackgroundCommandInfo | None", is_running: bool
) -> tuple[str, str]:
    """Return the state glyph and its style for a oneshot row."""
    if is_running:
        return _ONESHOT_RUN_GLYPH
    if oneshot_failed(info):
        return _ONESHOT_FAIL_GLYPH
    return _ONESHOT_OK_GLYPH


def oneshot_age(start: str | None, *, now: datetime | None = None) -> str | None:
    """Return a compact ``1m``-style age for an ISO timestamp, or ``None``.

    Compared in the configured timezone; *now* is a naive configured-timezone
    reference (default :func:`~sase.core.time.local_now`).
    """
    # Resolved via the bgcmd_list namespace at call time so tests that
    # patch ``sase.ace.tui.widgets.bgcmd_list.get_timezone`` /
    # ``local_now`` keep controlling this helper after the split.
    from .bgcmd_list import get_timezone, local_now

    if not start:
        return None
    try:
        moment = datetime.fromisoformat(start)
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(get_timezone()).replace(tzinfo=None)
    seconds = int(((now or local_now()) - moment).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def oneshot_chip(
    info: "BackgroundCommandInfo | None", is_running: bool
) -> tuple[str, str] | None:
    """Return the trailing status chip: run time or recorded exit + age."""
    if info is None:
        return None
    if is_running:
        age = oneshot_age(info.started_at)
        label = "running" if age is None else f"running · {age}"
        return (label, _ONESHOT_RUN_CHIP_STYLE)
    if info.status == "killed":
        label, style = "killed", _ONESHOT_FAIL_CHIP_STYLE
    elif info.exit_code is not None:
        label = f"exit {info.exit_code}"
        style = (
            _ONESHOT_OK_CHIP_STYLE if info.exit_code == 0 else _ONESHOT_FAIL_CHIP_STYLE
        )
    elif info.status == "error":
        label, style = "error", _ONESHOT_FAIL_CHIP_STYLE
    else:
        label, style = "done", _ONESHOT_DONE_CHIP_STYLE
    age = oneshot_age(info.finished_at)
    return (label if age is None else f"{label} · {age} ago", style)


__all__ = [
    "oneshot_age",
    "oneshot_chip",
    "oneshot_failed",
    "oneshot_glyph",
]
