"""Shared healer plumbing: models, ledger annotations, and notifications.

Public names in this private module are the only cross-module sharing
point for the healer split. Every other healer module keeps its
``_``-prefixed helpers local and imports shared behavior from here.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HealerTarget:
    """One failure the healer should attempt."""

    artifacts_dir: Path
    project: str
    agent_name: str
    died_at: float | None = None


@dataclass(frozen=True)
class HealerOutcome:
    """What one healer pass did with one target."""

    action: str
    reason: str
    reason_text: str
    ledger_key: str | None = None
    launched_artifacts_dir: str | None = None
    evidence_dir: str | None = None


@dataclass(frozen=True)
class SkipDecision:
    """One skip-rule evaluation."""

    skip: bool
    decline_reason: str = ""
    reason_text: str = ""
    loud: bool = True


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def apply_skip_rules(
    target: HealerTarget,
    *,
    done: Mapping[str, Any],
    meta: Mapping[str, Any],
) -> SkipDecision:
    """Apply the user-intent skip rules against fresh state (re-validated)."""
    if meta.get("auto_restart") is not None:
        return SkipDecision(
            skip=True,
            decline_reason="already_restarted",
            reason_text="auto-restart skipped — already restarted once",
        )
    if _is_remote_done(done, meta):
        return SkipDecision(
            skip=True,
            decline_reason="remote",
            reason_text="auto-restart skipped — remote agent",
            loud=False,
        )
    if _outcome_is_killed(done):
        return SkipDecision(
            skip=True,
            decline_reason="killed",
            reason_text="auto-restart skipped — agent was killed or stopped",
            loud=False,
        )
    if str(done.get("outcome", "")) != "failed":
        return SkipDecision(
            skip=True,
            decline_reason="no_longer_failed",
            reason_text="auto-restart skipped — row is no longer failed",
            loud=False,
        )
    if _find_moved_on(target, meta):
        return SkipDecision(
            skip=True,
            decline_reason="manual_relaunch",
            reason_text="auto-restart skipped — already relaunched by hand",
            loud=False,
        )
    if _has_pending_marker(target, meta):
        return SkipDecision(
            skip=True,
            decline_reason="needs_user_decision",
            reason_text="not restarted — holding a question, plan, or gate marker",
        )
    return SkipDecision(skip=False)


def _is_remote_done(done: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
    for mapping in (done, meta):
        value = mapping.get("is_remote") if isinstance(mapping, Mapping) else None
        if value is True:
            return True
    return False


def _outcome_is_killed(done: Mapping[str, Any]) -> bool:
    outcome = str(done.get("outcome", ""))
    if outcome in ("killed", "stopped", "cancelled", "canceled"):
        return True
    kill_source = str(done.get("kill_source") or "")
    return bool(kill_source) and outcome != "failed"


def _find_moved_on(target: HealerTarget, meta: Mapping[str, Any]) -> bool:
    """Return whether the user already handled this failure by hand.

    True when the name now resolves to a different artifacts dir (a manual
    ``,x`` or relaunch won the race), or when the name is gone from the
    index *and* the failed row itself is gone (dismissed or wiped). A
    missing index entry with the failed row still on disk is a stale
    index, not user intent: the ledger still guards at-most-once.
    """
    try:
        from sase.agent.names._lookup_named import find_named_agent
    except Exception:
        return False
    name = str(meta.get("name") or meta.get("workflow_name") or "")
    if not name:
        return False
    try:
        agent = find_named_agent(name)
    except Exception:
        return False
    if agent is None:
        return not (target.artifacts_dir / "done.json").is_file()
    try:
        current = str(Path(str(agent.artifacts_dir)).resolve())
        wanted = str(target.artifacts_dir.resolve())
    except OSError:
        return False
    return current != wanted


def _has_pending_marker(target: HealerTarget, meta: Mapping[str, Any]) -> bool:
    try:
        from sase.agent.auto_restart.inputs import pending_handoff
        from sase.agent.auto_restart.inputs import pending_question
    except Exception:
        return False
    try:
        if bool(pending_question(target.artifacts_dir, meta)):
            return True
    except Exception:
        pass
    try:
        if bool(pending_handoff(target.artifacts_dir)):
            return True
    except Exception:
        pass
    return False


def annotate_record(
    stored: Any,
    *,
    decline_reason: str | None = None,
    launched_artifacts_dir: str | None = None,
    evidence_dir: str | None = None,
    episode_id: str | None = None,
    planned_name: str | None = None,
) -> Any:
    """Persist annotation-only wire fields without a state transition."""
    import dataclasses

    from sase.agent.auto_restart import ledger as ledger_mod

    record = stored.record
    changes: dict[str, Any] = {}
    if decline_reason is not None:
        changes["decline_reason"] = decline_reason
    if launched_artifacts_dir is not None:
        changes["launched_artifacts_dir"] = launched_artifacts_dir
    if evidence_dir is not None:
        changes["evidence_dir"] = evidence_dir
    if episode_id is not None:
        changes["episode_id"] = episode_id
    if planned_name is not None:
        changes["planned_name"] = planned_name
    if not changes:
        return stored
    return ledger_mod.store_ledger_record(
        ledger_mod.StoredLedgerRecord(
            record=dataclasses.replace(record, **changes), extra=dict(stored.extra)
        )
    )


def defer_heal(
    stored: Any, target: HealerTarget, detail: str, *, now: float
) -> HealerOutcome:
    from sase.agent.auto_restart import ledger as ledger_mod

    stored = ledger_mod.advance_ledger_record(stored, "defer", note=detail)
    write_recovery(target, "deferred", detail, now=now)
    return HealerOutcome(
        action="deferred",
        reason="deferred",
        reason_text=detail,
        ledger_key=stored.record.key,
    )


def decline_heal(
    stored: Any,
    target: HealerTarget,
    reason: str,
    reason_text: str,
    *,
    now: float,
    dry_run: bool,
    escalate: bool = False,
    episode_id: str | None = None,
    escalate_kind: str = "decline",
) -> HealerOutcome:
    from sase.agent.auto_restart import ledger as ledger_mod

    if not dry_run:
        stored = ledger_mod.advance_ledger_record(stored, "decline", note=reason)
        stored = annotate_record(stored, decline_reason=reason)
        write_recovery(target, "declined", reason_text, now=now)
        if escalate:
            escalate_healer(
                target, reason_text, episode_id=episode_id, kind=escalate_kind
            )
        else:
            resurface_healer(target, reason_text)
    return HealerOutcome(
        action="declined",
        reason=reason,
        reason_text=reason_text,
        ledger_key=stored.record.key,
    )


def escalate_healer(
    target: HealerTarget,
    reason_text: str,
    *,
    episode_id: str | None,
    kind: str = "decline",
) -> None:
    """Escalate one declined restart with the per-situation loud copy."""
    from sase.agent.auto_restart.notify import publish_escalation

    if kind == "storm":
        title = f"Auto-restart paused: {reason_text[:200]}"
        detail = (
            f"Episode {episode_id or 'unknown'}. Triage the failures, then run "
            "`sase agent auto-restart resume` to re-arm."
        )
    elif kind == "post_provider":
        title = (
            f"{target.agent_name} broke after its model turn during a sase "
            "update — workspace held with its changes. "
            "Review, then ,x to relaunch."
        )
        detail = reason_text
    elif kind == "already_restarted":
        episode = f" after sase update {episode_id}" if episode_id else ""
        title = (
            f"This was its automatic restart{episode} — not retrying. "
            f"Press ,x on {target.agent_name} to retry by hand."
        )
        detail = reason_text
    else:
        title = (
            f"Couldn't restart {target.agent_name} automatically — {reason_text[:160]}"
        )
        detail = (
            f"{target.agent_name} broke during a sase update but was left alone: "
            f"{reason_text} Press ,x on it to retry by hand."
        )
    with contextlib.suppress(Exception):
        publish_escalation(
            agent_name=target.agent_name,
            title=title,
            detail=detail,
            episode_id=episode_id,
            kind=kind if kind == "storm" else "decline",
            artifacts_dir=str(target.artifacts_dir),
        )


def resurface_healer(target: HealerTarget, reason_text: str) -> None:
    from sase.agent.auto_restart.notify import resurface_failure

    with contextlib.suppress(Exception):
        resurface_failure(
            agent_name=target.agent_name,
            reason_text=reason_text,
            artifacts_dir=str(target.artifacts_dir),
        )


def publish_relaunch_event(
    target: HealerTarget,
    *,
    verdict: Any,
    episode_id: str | None,
    evidence_dir: str | None,
) -> None:
    from sase.agent.auto_restart.notify import publish_relaunch

    files = [evidence_dir] if evidence_dir else []
    with contextlib.suppress(Exception):
        publish_relaunch(
            episode_id=episode_id or "unknown",
            agent_name=target.agent_name,
            update_ref=episode_id or "unknown",
            reason_text=getattr(verdict, "reason_text", "") or "",
            evidence_files=files,
        )


def write_recovery(
    target: HealerTarget, state: str, note: str, *, now: float | None = None
) -> None:
    """Write the ``recovery`` object on the failed row's ``done.json``."""
    import datetime

    from sase.core.time import get_timezone

    at = time.time() if now is None else now
    path = target.artifacts_dir / "done.json"
    done = read_json(path) or {}
    try:
        previous = done.get("recovery")
        episode_id = previous.get("episode_id") if isinstance(previous, dict) else None
    except AttributeError:
        episode_id = None
    done["recovery"] = {
        "state": state,
        "reason": note[:200] if state == "declined" else None,
        "reason_text": note,
        "requested_at": (
            previous.get("requested_at")
            if isinstance(previous, dict) and previous.get("requested_at")
            else datetime.datetime.fromtimestamp(at, tz=get_timezone()).isoformat()
        ),
        "updated_at": datetime.datetime.fromtimestamp(
            at, tz=get_timezone()
        ).isoformat(),
        "episode_id": episode_id,
    }
    try:
        from sase.notification_gates.durability import atomic_write_json

        atomic_write_json(path, done)
    except OSError:
        return
    with contextlib.suppress(Exception):
        from sase.core.agent_artifact_index_lifecycle_mutations import (
            update_agent_artifact_index_for_marker_mutation,
        )

        update_agent_artifact_index_for_marker_mutation(target.artifacts_dir)


__all__ = [
    "HealerOutcome",
    "HealerTarget",
    "SkipDecision",
    "annotate_record",
    "apply_skip_rules",
    "decline_heal",
    "defer_heal",
    "escalate_healer",
    "publish_relaunch_event",
    "read_json",
    "resurface_healer",
    "write_recovery",
]
