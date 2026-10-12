"""One-shot post-update notice for the Artifacts Agent pane retirement.

Agent history moved from the Artifacts tab's Agent sub-tab to the Agents
tab's Archive view. This persists a plain "seen" marker under
:func:`sase_home` so the explanation shows at most once, ever.

The caller (``StartupLoadsMixin``) only invokes this after
``_maybe_show_post_update_toast`` reports that a real pending update receipt
was just consumed — i.e. this is genuinely the first ACE run after an update
brought in the change, not merely the first mount of any fresh app instance.
That keeps brand new installs (which never saw the old pane) and headless
tests (which never populate an update receipt) silent, while still writing
the marker exactly once for an existing user's first post-update session.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sase.core.paths import sase_home

log = logging.getLogger(__name__)

_MARKER_FILENAME = "artifacts_agent_pane_retired_notice_shown"


def has_shown_artifacts_agent_pane_notice() -> bool:
    """Return whether the one-time notice has already been shown."""
    return _marker_path().exists()


def mark_artifacts_agent_pane_notice_shown() -> None:
    """Persist that the one-time notice has been shown, best-effort."""
    path = _marker_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
    except OSError:
        log.debug("Failed to persist artifacts agent pane notice marker", exc_info=True)


def _marker_path() -> Path:
    return sase_home() / _MARKER_FILENAME


__all__ = [
    "has_shown_artifacts_agent_pane_notice",
    "mark_artifacts_agent_pane_notice_shown",
]
