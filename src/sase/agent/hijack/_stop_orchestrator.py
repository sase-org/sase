"""The ordered stop protocol for Agent Hijack (phase ``stop``)."""

from __future__ import annotations

import logging
import socket
import uuid
from dataclasses import dataclass
from typing import Any

from sase.agent.hijack._stop_claim import (
    abort_before_stop,
    ensure_hijacked_settlement,
    pin_claim,
    remove_intent,
    terminate_tree,
    unpin_claim,
)
from sase.agent.hijack._stop_evidence import (
    attach_evidence,
    capture_snapshots,
    collect_evidence,
    format_diff_summary,
)
from sase.agent.hijack._stop_models import HijackTarget, StopDeps, read_done_marker
from sase.agent.hijack._stop_target import resolve_target

LOG = logging.getLogger(__name__)

#: Source tag recorded in the user-kill intent marker.
STOP_INTENT_SOURCE = "agent_hijack"

_EXIT_HELD = 0
_EXIT_REFUSED = 2
_EXIT_FAILED = 1


@dataclass
class HijackStopResult:
    """Outcome of one stop-orchestrator run."""

    status: str
    message: str
    exit_code: int
    hijack_id: str | None = None
    record: dict[str, Any] | None = None
    reason: str | None = None


def _new_hijack_id(agent_name: str) -> str:
    """Return a filesystem-safe unique id for one hijack attempt."""
    cleaned = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in agent_name
    ).strip("_")
    return f"hijack-{cleaned or 'agent'}-{uuid.uuid4().hex[:12]}"


def stop_agent_for_hijack(
    name: str,
    *,
    reason: str | None = None,
    hijack_id: str | None = None,
    source: str = STOP_INTENT_SOURCE,
    deps: StopDeps | None = None,
) -> HijackStopResult:
    """Run the ordered stop orchestrator for *name*.

    Exit codes follow the CLI contract: 0 means HIJACKED, 2 means refused
    with nothing changed, and 1 means stop failed or an error occurred.
    """
    deps = deps or StopDeps()
    target = resolve_target(name, deps=deps)
    if target is None:
        return HijackStopResult(
            status="refused",
            message=f"No agent found with name '{name}'",
            exit_code=_EXIT_REFUSED,
            reason="not_found",
        )
    if target.done_outcome is not None and target.done_outcome != "hijacked":
        return HijackStopResult(
            status="refused",
            message=(
                f"Agent '{name}' already completed ({target.done_outcome}); "
                f"nothing to hijack"
            ),
            exit_code=_EXIT_REFUSED,
            reason="already_completed",
        )
    decision = _check_eligibility(target)
    if not decision.get("eligible", False):
        return HijackStopResult(
            status="refused",
            message=(
                f"Cannot hijack agent '{name}': "
                f"{decision.get('message') or 'not eligible'}"
            ),
            exit_code=_EXIT_REFUSED,
            reason=str(decision.get("code") or "ineligible"),
        )

    from sase.agent.hijack import ledger

    resolved_id = hijack_id or _new_hijack_id(name)
    record = ledger.new_requested_record(
        hijack_id=resolved_id,
        agent_name=target.name,
        artifacts_dir=target.artifacts_dir,
        pid=target.pid,
        project_file=None if target.is_home else target.project_file,
        workspace_num=target.workspace_num,
        workspace_dir=target.workspace_dir,
        expected_claim_owner_pid=target.claim_pid,
        session=target.agent_session,
        host=_local_host(),
        model_alias=target.model_alias,
        model_alias_trail=target.model_alias_trail,
        model_origin=target.model_origin,
        provider=target.provider,
        model=target.model,
        effort=target.effort,
    )
    record["prior_pin_state"] = bool(target.claim_pinned)
    try:
        record = ledger.create_record(record)
    except FileExistsError as exc:
        return HijackStopResult(
            status="error",
            message=f"Hijack record {resolved_id} already exists: {exc}",
            exit_code=_EXIT_FAILED,
            hijack_id=resolved_id,
            reason="record_exists",
        )

    from sase.agent._user_kill_intent import write_user_kill_intent

    write_user_kill_intent(
        target.artifacts_dir,
        pid=int(target.pid or 0),
        source=source,
        reason=reason,
        mode="hijack",
        hijack_id=resolved_id,
    )

    pinned_by_us = False
    if not target.is_home and target.workspace_num is not None:
        pin = pin_claim(target)
        if not pin:
            abort_before_stop(
                target, resolved_id, reason="claim mismatch; not hijacked"
            )
            return HijackStopResult(
                status="error",
                message=(
                    f"Cannot hijack agent '{name}': its workspace claim changed "
                    f"while preparing; nothing was signalled"
                ),
                exit_code=_EXIT_FAILED,
                hijack_id=resolved_id,
                reason="claim_mismatch",
            )
        pinned_by_us = not target.claim_pinned

    try:
        record = ledger.cas_advance_record(record, {"event": "begin_stop"})
    except Exception as exc:
        abort_before_stop(target, resolved_id, reason=str(exc))
        return HijackStopResult(
            status="error",
            message=f"Could not start hijack of agent '{name}': {exc}",
            exit_code=_EXIT_FAILED,
            hijack_id=resolved_id,
            reason="record_advance_failed",
        )

    lost = _read_done_outcome(target.artifacts_dir)
    if lost is not None and lost != "hijacked":
        try:
            finished = ledger.cas_advance_record(record, {"event": "finished_first"})
        except Exception:
            finished = ledger.load_record(resolved_id) or record
        remove_intent(target.artifacts_dir)
        if pinned_by_us:
            unpin_claim(target)
        return HijackStopResult(
            status="finished_first",
            message=(
                f"Agent '{name}' finished first ({lost}); its real outcome "
                f"was kept and nothing was stopped"
            ),
            exit_code=_EXIT_REFUSED,
            hijack_id=resolved_id,
            record=finished,
            reason="finished_first",
        )

    termination = terminate_tree(target, deps=deps)
    if not termination.success:
        survivors = [int(pid) for pid in (termination.survivors or ())]
        try:
            failed = ledger.cas_advance_record(
                record,
                {
                    "event": "stop_failed",
                    "error": termination.error or f"survivor pids: {survivors}",
                    "survivor_pids": survivors,
                },
            )
        except Exception:
            failed = ledger.load_record(resolved_id) or record
        remove_intent(target.artifacts_dir)
        if pinned_by_us:
            unpin_claim(target)
        detail = f" (pids {', '.join(map(str, survivors))})" if survivors else ""
        return HijackStopResult(
            status="stop_failed",
            message=(
                f"Could not fully stop agent '{name}'{detail}; it is still "
                f"RUNNING and nothing was held"
            ),
            exit_code=_EXIT_FAILED,
            hijack_id=resolved_id,
            record=failed,
            reason="stop_failed",
        )

    ensure_hijacked_settlement(target, resolved_id, pinned_by_us)
    try:
        record = ledger.load_record(resolved_id) or record
    except Exception:
        pass
    evidence_error: str | None = None
    try:
        evidence = collect_evidence(target, deps=deps)
        attach_evidence(resolved_id, evidence)
        record = ledger.load_record(resolved_id) or record
    except Exception as exc:  # noqa: BLE001 - evidence is best-effort.
        evidence_error = str(exc)
        LOG.warning("hijack evidence collection failed: %s", exc)
    try:
        snapshots, snapshot_error = capture_snapshots(target, deps=deps)
        if snapshots:
            attach_evidence(resolved_id, {"snapshots": snapshots})
        if snapshot_error and not evidence_error:
            evidence_error = snapshot_error
        if snapshot_error:
            attach_evidence(
                resolved_id, {"error": f"snapshot failed: {snapshot_error}"}
            )
        record = ledger.load_record(resolved_id) or record
    except Exception as exc:  # noqa: BLE001 - snapshots never block held.
        if not evidence_error:
            evidence_error = str(exc)
        LOG.warning("hijack snapshot failed: %s", exc)
    try:
        held = ledger.cas_advance_record(record, {"event": "confirmed_stop"})
    except Exception as exc:
        return HijackStopResult(
            status="error",
            message=(
                f"Agent '{name}' was stopped but the hijack record could not "
                f"be published: {exc}"
            ),
            exit_code=_EXIT_FAILED,
            hijack_id=resolved_id,
            record=ledger.load_record(resolved_id) or record,
            reason="publish_failed",
        )
    summary = format_diff_summary(held)
    held_suffix = f" · {summary}" if summary else ""
    if evidence_error:
        held_suffix += f" (snapshot pending: {evidence_error})"
    return HijackStopResult(
        status="held",
        message=(
            f"\u23cf hijacked {name} \u00b7 ws #{target.workspace_num} held"
            f"{held_suffix} \u00b7 next: sase agent recover {name}"
        ),
        exit_code=_EXIT_HELD,
        hijack_id=resolved_id,
        record=held,
    )


def _local_host() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return ""


def _read_done_outcome(artifacts_dir: str) -> str | None:
    outcome, _ = read_done_marker(artifacts_dir)
    return outcome


def _check_eligibility(target: HijackTarget) -> dict[str, Any]:
    from sase.agent.hijack.core import agent_hijack_eligibility

    facts = {
        "schema_version": 1,
        "is_local": True,
        "is_llm_agent": True,
        "is_monitor_turn": target.is_monitor_turn,
        "is_gate_turn": target.is_gate_turn,
        "is_named_proc": False,
        "is_home_mode": target.is_home,
        "is_remote": False,
        "is_clan_container": False,
        "is_bulk": False,
        "workspace_num": target.workspace_num,
        "status": target.status,
        "lifecycle_phase": target.lifecycle_phase,
        "has_hijack_capability": "hijack" in target.capabilities,
        "pid": target.pid,
    }
    return dict(agent_hijack_eligibility(facts))


__all__ = [
    "HijackStopResult",
    "STOP_INTENT_SOURCE",
    "stop_agent_for_hijack",
]
