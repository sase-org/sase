"""Kitty-graphics capability probe for terminal video artifacts.

Deferred: only the inspect view (itself deferred off TUI first paint) imports
this module, so none of its names may be re-exported from the eager facades
(``graphics/__init__.py``, ``_viewer_loop.py``, ``viewer.py``).
"""

from __future__ import annotations

import os
import subprocess

_KITTY_GRAPHICS_TERM_NAMES = ("kitty", "ghostty")
_KITTY_GRAPHICS_CACHE: bool | None = None


def _term_name_advertises_kitty_graphics(value: str | None) -> bool:
    """Return whether a terminal name implies kitty-graphics support."""

    if not value:
        return False
    lowered = value.lower()
    return any(name in lowered for name in _KITTY_GRAPHICS_TERM_NAMES)


def _tmux_client_termname_once(*, timeout: float = 1.0) -> str | None:
    """Return the tmux client's terminal name, or ``None`` when unreadable."""

    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{client_termname}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        if line.strip():
            return line.strip()
    return None


def kitty_graphics_capable(*, force: bool = False) -> bool:
    """Return whether the terminal can display kitty graphics.

    Outside tmux this matches ``TERM`` against the kitty family names or
    accepts a set ``KITTY_WINDOW_ID``. Inside tmux the TUI's own environment
    is the session's, so one bounded ``tmux display-message`` reads the
    attached client's ``client_termname`` instead. The result is cached for
    the viewer process.
    """

    global _KITTY_GRAPHICS_CACHE
    if _KITTY_GRAPHICS_CACHE is not None and not force:
        return _KITTY_GRAPHICS_CACHE
    from ._viewer_tmux_common import is_tmux_session

    if is_tmux_session():
        capable = _term_name_advertises_kitty_graphics(_tmux_client_termname_once())
    else:
        capable = _term_name_advertises_kitty_graphics(os.environ.get("TERM")) or bool(
            os.environ.get("KITTY_WINDOW_ID")
        )
    _KITTY_GRAPHICS_CACHE = capable
    return capable


__all__ = [
    "kitty_graphics_capable",
]
