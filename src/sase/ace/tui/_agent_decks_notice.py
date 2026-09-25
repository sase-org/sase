"""One-shot post-update notice for the agent data decks cut-over.

The Agents tab replaced its metadata panel plus one File or LLM Calls panel, the
``p`` view picker, and the ``Z`` zoom modal with one or two deck panels showing
agent data decks (Main, Files, Tools) made of agent data cards. This persists a
plain "seen" marker under :func:`sase_home` so the explanation shows at most
once, ever.

The caller (``StartupLoadsMixin``) only invokes this after
``_maybe_show_post_update_toast`` reports that a real pending update receipt
was just consumed — i.e. this is genuinely the first ACE run after an update
brought in the change, not merely the first mount of any fresh app instance.
That keeps brand new installs (which never saw the old picker) and headless
tests (which never populate an update receipt) silent, while still writing
the marker exactly once for an existing user's first post-update session.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sase.core.paths import sase_home

log = logging.getLogger(__name__)

_MARKER_FILENAME = "agent_decks_notice_shown"


def has_shown_agent_decks_notice() -> bool:
    """Return whether the one-time notice has already been shown."""
    return _marker_path().exists()


def mark_agent_decks_notice_shown() -> None:
    """Persist that the one-time notice has been shown, best-effort."""
    path = _marker_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
    except OSError:
        log.debug("Failed to persist agent decks notice marker", exc_info=True)


def _marker_path() -> Path:
    return sase_home() / _MARKER_FILENAME


__all__ = [
    "has_shown_agent_decks_notice",
    "mark_agent_decks_notice_shown",
]
