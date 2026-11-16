"""Target dedup helpers for the hijack stop protocol."""

from __future__ import annotations

from typing import Any

from sase.agent.hijack._stop_models import HijackTarget
from sase.agent.hijack._stop_orchestrator_common import (
    EXIT_FAILED,
    EXIT_HELD,
    EXIT_LATCHED,
    HijackStopResult,
)


def _target_key_name(subject: Any, target: HijackTarget) -> str:
    """Return the session-or-agent name component of the target key."""
    session = getattr(subject, "session", None)
    base_name = getattr(session, "base_name", None)
    if isinstance(base_name, str) and base_name:
        return base_name
    agent_session = getattr(target, "agent_session", None)
    if isinstance(agent_session, str) and agent_session:
        return agent_session
    return target.name


def compute_target_key(subject: Any, target: HijackTarget) -> str:
    """Return the session-stable ledger key for one stop target."""
    from sase.agent.hijack import ledger

    project_file: str | None = None
    if not target.is_home:
        project_file = target.project_file
    return ledger.target_key_for(project_file, _target_key_name(subject, target))


def target_identity(target: HijackTarget | None) -> tuple[Any, ...] | None:
    """Return the identity tuple used to detect occupant changes."""
    if target is None:
        return None
    return (
        target.name,
        target.project_file,
        target.artifacts_timestamp,
        target.artifacts_dir,
        target.pid,
        target.claim_pid,
        target.workspace_num,
        target.agent_session,
        target.is_home,
    )


def coalesced_result(
    name: str,
    active: dict[str, Any],
    *,
    subject: Any,
    decision: dict[str, Any] | None = None,
) -> HijackStopResult:
    """Return the active operation instead of starting a second stop."""
    state = str(active.get("state") or "")
    hijack_id = active.get("hijack_id")
    hijack_id_str = hijack_id if isinstance(hijack_id, str) else None
    workspace_num = active.get("workspace_num")
    try:
        workspace_num_int = int(workspace_num) if workspace_num is not None else None
    except (TypeError, ValueError):
        workspace_num_int = None
    if state == "held":
        return HijackStopResult(
            status="held",
            message=(
                f"Hijack {hijack_id_str} already holds "
                f"{active.get('agent_name') or name}; nothing else was stopped"
            ),
            exit_code=EXIT_HELD,
            hijack_id=hijack_id_str,
            record=dict(active),
            reason="already_held",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=workspace_num_int,
        )
    if state == "latched":
        boundary = active.get("boundary")
        boundary_text = (
            str(boundary).replace("_", " ")
            if isinstance(boundary, str) and boundary
            else "hand-off"
        )
        return HijackStopResult(
            status="latched",
            message=(
                f"\u23cf hijack latched for {active.get('agent_name') or name} "
                f"\u00b7 applies after {boundary_text} "
                f"\u00b7 next: sase agent hijack -c {name} to cancel"
            ),
            exit_code=EXIT_LATCHED,
            hijack_id=hijack_id_str,
            record=dict(active),
            reason="latched",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=workspace_num_int,
        )
    if state == "stop_blocked":
        survivors = active.get("survivor_pids") or []
        detail = ""
        try:
            count = len(list(survivors))
            if count:
                detail = f" ({count} processes survived)"
        except TypeError:
            detail = ""
        return HijackStopResult(
            status="stop_blocked",
            message=(
                f"Hijack {hijack_id_str} is already blocked{detail}; "
                "workspace kept; `,k` retries, or release with x"
            ),
            exit_code=EXIT_FAILED,
            hijack_id=hijack_id_str,
            record=dict(active),
            reason="stop_blocked",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=workspace_num_int,
        )
    return HijackStopResult(
        status="active",
        message=(
            f"Hijack {hijack_id_str} is already {state or 'in progress'}; "
            "returning the active operation instead of starting a second stop"
        ),
        exit_code=EXIT_HELD,
        hijack_id=hijack_id_str,
        record=dict(active),
        reason="already_active",
        decision=decision,
        occupant_name=getattr(subject, "occupant_name", None),
        occupant_reason=getattr(subject, "occupant_reason", None),
        workspace_num=workspace_num_int,
    )


__all__ = [
    "coalesced_result",
    "compute_target_key",
    "target_identity",
]
