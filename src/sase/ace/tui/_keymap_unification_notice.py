"""One-shot post-update notice for the sase-m6.9 keymap unification.

``y`` flipping from "refresh" to "copy reference" on the Patches pane is the
single most jarring default-keybinding change in that unification (Patch was
the only pane where ``y`` meant refresh; every sibling pane already used
``y`` to copy and ``R`` to refresh). This persists a plain "seen" marker
under :func:`sase_home` so the explanation shows at most once, ever.

The caller (``StartupLoadsMixin``) only invokes this after
``_maybe_show_post_update_toast`` reports that a real pending update receipt
was just consumed — i.e. this is genuinely the first ACE run after an update
brought in the change, not merely the first mount of any fresh app instance.
That keeps brand new installs (which never saw the old binding) and headless
tests (which never populate an update receipt) silent, while still writing
the marker exactly once for an existing user's first post-update session.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sase.core.paths import sase_home

log = logging.getLogger(__name__)

_MARKER_FILENAME = "keymap_unification_sase_m6_9_notice_shown"


def has_shown_keymap_unification_notice() -> bool:
    """Return whether the one-time notice has already been shown."""
    return _marker_path().exists()


def mark_keymap_unification_notice_shown() -> None:
    """Persist that the one-time notice has been shown, best-effort."""
    path = _marker_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
    except OSError:
        log.debug("Failed to persist keymap unification notice marker", exc_info=True)


def _marker_path() -> Path:
    return sase_home() / _MARKER_FILENAME


__all__ = [
    "has_shown_keymap_unification_notice",
    "mark_keymap_unification_notice_shown",
]
