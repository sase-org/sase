"""Shared ⚐ stranded-work presentation vocabulary.

ACE, doctor, and later surfaces import from here so wording and styles never
drift. Rich style strings only; no Textual imports.
"""

from __future__ import annotations

from sase.core.stranded_work_facade import StrandedWorkVerdict

STRANDED_GLYPH = "⚐"
STRANDED_WORD = "STRANDED"
STRANDED_LEAF_STYLE = "bold #FFAF00"
STRANDED_BREADCRUMB_STYLE = "#AF8700"

_CAUSE_SENTENCES = {
    "failed": "latest turn failed; nothing resumes it",
    "stopped": "latest turn was stopped; nothing resumes it",
    "lost": "latest turn is gone; nothing resumes it",
    "child_landed": "child epic landed; the phase is still open",
    "close_failed": "ended with bead_action close; the bead is still open",
    "kept": "ended with bead_action keep; nothing resumes it",
    "unclosed": "ended without closing the bead; nothing resumes it",
}


def stranded_cause_sentence(verdict: StrandedWorkVerdict) -> str:
    """Return the short cause sentence for a stranded verdict."""
    reason = (verdict.reason or "").strip()
    if reason == "followup_failed":
        member = verdict.last_turn or verdict.session or "the latest turn"
        return f"{member} follow-up failed; nothing resumes it"
    return _CAUSE_SENTENCES.get(reason, "nothing resumes it")


def stranded_age_label(since: float | None, now: float) -> str:
    """Return compact age since *since* (``31h``, ``2d``), or ``""``."""
    if since is None:
        return ""
    delta = max(0, int(now - since))
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    if delta < 30 * 86400:
        return f"{delta // 86400}d"
    if delta < 365 * 86400:
        return f"{delta // (30 * 86400)}mo"
    return f"{delta // (365 * 86400)}y"


def blocked_sentence(verdict: StrandedWorkVerdict) -> str:
    """Return ``blocked by stranded <leaf> (+N more)``, or ``""``."""
    blocked_by = verdict.blocked_by
    if not blocked_by:
        return ""
    leaf = blocked_by[0]
    extra = len(blocked_by) - 1
    if extra:
        return f"blocked by stranded {leaf} (+{extra} more)"
    return f"blocked by stranded {leaf}"


__all__ = [
    "STRANDED_BREADCRUMB_STYLE",
    "STRANDED_GLYPH",
    "STRANDED_LEAF_STYLE",
    "STRANDED_WORD",
    "blocked_sentence",
    "stranded_age_label",
    "stranded_cause_sentence",
]
