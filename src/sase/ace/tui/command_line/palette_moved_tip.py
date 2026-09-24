"""One-time tip shown after the ``:``/``;`` flip landed.

``:`` used to open the Command Palette; it now opens the Command Line while
the palette moved to ``;``. The first time the panel opens, the hint row
says so. This persists a plain "seen" marker under :func:`sase_home` so the
tip shows at most once, ever, following ``_keymap_unification_notice.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sase.core.paths import sase_home

log = logging.getLogger(__name__)

_MARKER_FILENAME = "command_line_palette_moved_tip_shown"

#: Hint-row text shown once, on the first panel open after the flip.
COMMAND_LINE_PALETTE_MOVED_TIP = "Command Palette moved to `;` (type `;` here to jump)"


def has_shown_palette_moved_tip() -> bool:
    """Return whether the one-time tip has already been shown."""
    return _marker_path().exists()


def mark_palette_moved_tip_shown() -> None:
    """Persist that the one-time tip has been shown, best-effort."""
    path = _marker_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
    except OSError:
        log.debug("Failed to persist palette-moved tip marker", exc_info=True)


def _marker_path() -> Path:
    return sase_home() / _MARKER_FILENAME


__all__ = [
    "COMMAND_LINE_PALETTE_MOVED_TIP",
    "has_shown_palette_moved_tip",
    "mark_palette_moved_tip_shown",
]
