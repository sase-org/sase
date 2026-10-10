"""Presentation helpers for update-skew auto-restart UX surfaces.

Pure functions only: no disk I/O, no subprocesses, no config reads. The
callers (done-wire loaders) supply ``now`` and thresholds, so render paths
stay free of per-keypress work and these helpers stay trivially testable.
"""

from __future__ import annotations

from datetime import datetime
from collections.abc import Mapping
from typing import Any

from sase.agent.auto_restart.constants import UPDATE_RECOVERY_GLYPH
from sase.core.time import get_timezone, parse_local

RESTARTING_STATUS = "RESTARTING"
RESTARTING_STYLE = "bold #FFAF5F"
RESTARTING_HINT_STYLE = "dim"

#: done.json ``recovery.state`` values that render as in-flight.
RECOVERY_IN_FLIGHT_STATES: tuple[str, ...] = (
    "pending",
    "deferred",
    "launching",
)

STALE_PENDING_HINT = "auto-restart never ran — is the sase scheduler running?"
DEFERRED_HINT = f"{UPDATE_RECOVERY_GLYPH} waiting for the sase update to finish"
PENDING_HINT = "restarting once the update settles"


def _recovery_is_in_flight(state: object) -> bool:
    """Return whether a done-marker recovery state renders as restarting."""
    if not isinstance(state, str):
        return False
    try:
        from sase.core.agent_auto_restart_facade import (
            auto_restart_recovery_is_in_flight,
        )
    except Exception:
        return state in RECOVERY_IN_FLIGHT_STATES
    try:
        return bool(auto_restart_recovery_is_in_flight(state))
    except Exception:
        return state in RECOVERY_IN_FLIGHT_STATES


def _parse_requested_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return parse_local(value)


def _is_stale_pending(
    state: object,
    requested_at: object,
    *,
    now: datetime | None = None,
    pending_resurface_seconds: float = 600,
) -> bool:
    """Return whether an in-flight ``pending`` recovery looks abandoned.

    True when *state* is ``pending`` and *requested_at* is older than
    *pending_resurface_seconds*. The healer and its scheduler sweep act
    within about a minute, so an older pending means no pass ever owned
    the failure.
    """
    if state != "pending":
        return False
    requested = _parse_requested_at(requested_at)
    if requested is None:
        return False
    reference = parse_local(now) if now is not None else datetime.now(get_timezone())
    if reference is None:
        return False
    try:
        age = (reference - requested).total_seconds()
    except (OverflowError, TypeError):
        return False
    return age > pending_resurface_seconds


def _episode_short(episode_id: object) -> str | None:
    if not isinstance(episode_id, str) or not episode_id:
        return None
    short = episode_id.split("@")[-1][:12].strip()
    return short or None


def restarting_hint(
    state: object,
    *,
    reason_text: object = None,
    episode_id: object = None,
) -> str:
    """Return the dim hint shown after ``↻ RESTARTING`` for *state*."""
    if state == "deferred":
        return DEFERRED_HINT
    short = _episode_short(episode_id)
    if short:
        return f"sase updated to {short} · {PENDING_HINT}"
    if isinstance(reason_text, str) and reason_text.strip():
        return reason_text.strip()[:160]
    return f"sase updated · {PENDING_HINT}"


def declined_hint(
    reason: object = None,
    reason_text: object = None,
) -> str | None:
    """Return the dim ``FAILED`` hint for a declined recovery, if any."""
    if isinstance(reason_text, str) and reason_text.strip():
        return reason_text.strip()[:200]
    if isinstance(reason, str) and reason.strip():
        slug = reason.strip()
        return f"auto-restart skipped — {slug}"
    return None


def auto_restart_provenance_lines(provenance: Mapping[str, Any]) -> list[str]:
    """Return the replacement identity-header provenance block lines."""
    from_rev = provenance.get("from_rev")
    to_rev = provenance.get("to_rev")
    if isinstance(from_rev, str) and isinstance(to_rev, str) and from_rev and to_rev:
        first = (
            f"{UPDATE_RECOVERY_GLYPH} Auto-restarted after sase update "
            f"{from_rev} → {to_rev}"
        )
    else:
        culprit = provenance.get("culprit_commit")
        if isinstance(culprit, str) and culprit:
            first = (
                f"{UPDATE_RECOVERY_GLYPH} Auto-restarted after sase update "
                f"{culprit[:12]}"
            )
        else:
            first = f"{UPDATE_RECOVERY_GLYPH} Auto-restarted after a sase update"
    lines = [first]
    signature = provenance.get("signature")
    if isinstance(signature, str) and signature.strip():
        lines.append(f"  was: {signature.strip()[:160]}")
    else:
        lines.append("  was: broke before its model turn · nothing lost")
        return lines
    broke = provenance.get("broke_detail")
    if isinstance(broke, str) and broke.strip():
        lines.append(f"  {broke.strip()[:160]}")
    else:
        lines.append("  broke before its model turn · nothing lost")
    return lines


def _auto_restart_evidence_dir_path(provenance: Mapping[str, Any]) -> str | None:
    """Return the preserved evidence bundle directory for the ``v`` hint."""
    evidence_dir = provenance.get("evidence_dir")
    if not isinstance(evidence_dir, str) or not evidence_dir:
        return None
    return evidence_dir.rstrip("/")


def _pending_resurface_seconds(default: float = 600.0) -> float:
    try:
        from sase.config._settings_system import (
            get_agent_auto_restart_pending_resurface_seconds,
        )
    except Exception:
        return default
    try:
        return float(get_agent_auto_restart_pending_resurface_seconds())
    except Exception:
        return default


def apply_recovery_to_agent(
    agent: Any,
    *,
    state: object,
    reason: object = None,
    reason_text: object = None,
    requested_at: object = None,
    updated_at: object = None,
    episode_id: object = None,
    now: datetime | None = None,
    pending_resurface_seconds: float | None = None,
) -> str | None:
    """Project a done-marker recovery object onto a TUI agent row.

    Sets the ``recovery_*`` fields in place. Returns ``RESTARTING_STATUS``
    when the row should render as an in-flight recovery instead of
    ``FAILED``. A stale ``pending`` (older than the resurface threshold,
    so no healer pass ever owned it) stays ``FAILED`` and is flagged via
    ``recovery_stale_pending`` for the scheduler-hint rendering.
    """
    text_state = state if isinstance(state, str) else None
    agent.recovery_state = text_state
    agent.recovery_reason = reason if isinstance(reason, str) else None
    agent.recovery_reason_text = reason_text if isinstance(reason_text, str) else None
    agent.recovery_episode_id = episode_id if isinstance(episode_id, str) else None
    agent.recovery_requested_at = (
        requested_at if isinstance(requested_at, str) else None
    )
    agent.recovery_updated_at = updated_at if isinstance(updated_at, str) else None
    agent.recovery_stale_pending = False
    if not _recovery_is_in_flight(text_state):
        return None
    threshold = (
        pending_resurface_seconds
        if pending_resurface_seconds is not None
        else _pending_resurface_seconds()
    )
    if _is_stale_pending(
        text_state,
        requested_at,
        now=now,
        pending_resurface_seconds=threshold,
    ):
        agent.recovery_stale_pending = True
        return None
    return RESTARTING_STATUS


def apply_provenance_to_agent(agent: Any, provenance: object) -> None:
    """Project an ``agent_meta`` auto-restart record onto a TUI agent row.

    A set record marks the row as a same-name replacement and registers
    the preserved evidence bundle directory as a ``v`` file hint. Render
    paths never stat the bundle.
    """
    if not isinstance(provenance, Mapping):
        return
    record = dict(provenance)
    if not record:
        return
    agent.auto_restart_provenance = record
    evidence_dir = _auto_restart_evidence_dir_path(record)
    if evidence_dir is None:
        return
    extra = getattr(agent, "extra_files", None)
    if not isinstance(extra, list):
        return
    if evidence_dir not in extra:
        extra.append(evidence_dir)


__all__ = [
    "DEFERRED_HINT",
    "PENDING_HINT",
    "RECOVERY_IN_FLIGHT_STATES",
    "RESTARTING_HINT_STYLE",
    "RESTARTING_STATUS",
    "RESTARTING_STYLE",
    "STALE_PENDING_HINT",
    "apply_provenance_to_agent",
    "apply_recovery_to_agent",
    "auto_restart_provenance_lines",
    "declined_hint",
    "restarting_hint",
]
