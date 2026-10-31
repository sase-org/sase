"""Unwind unstarted staged-monitor resources.

Cleanup path of the internal staged-monitor transaction split from
:mod:`sase.monitor.start_stage`. Settles an owned reserved ToolRun as never
executed, releases only this stage's join reservation, and never stops an
already-running joined run.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from sase.agent.staged_handoff import discard_staged_handoff

from ._start_stage_shared import claim_context, optional_str
from ._start_stage_shared import prepared_intent_ref as shared_prepared_intent_ref
from .models import MonitorError
from .staged_owner import clear_staged_owner_index, launch_payload_path
from .start_metadata import read_start_meta
from .start_runtime import teardown_failed_member


@dataclass(frozen=True)
class _StagedMonitorCleanupResult:
    """Outcome of unwinding one unstarted staged monitor."""

    monitor_id: str
    staged_id: str | None
    held: bool
    released_join: bool
    settled_tool_run_id: str | None
    member_state: str
    released_prepared_intent: bool = False
    skipped: bool = False


def cleanup_staged_monitor(
    artifacts_dir: str,
    *,
    held: bool = False,
    join_mode: str | None = None,
    tool_run_id: str | None = None,
    staged_id: str | None = None,
    starter_artifacts_dir: str | None = None,
    prepared_intent_ref: str | None = None,
    tool_run_joined: bool = False,
) -> _StagedMonitorCleanupResult:
    """Unwind unstarted staged resources. Safe to repeat.

    Settles an owned reserved ToolRun as never executed. Releases only this
    stage's join reservation. Never stops an already-running joined run. A
    held cleanup keeps the outer staged record.
    """
    try:
        meta = read_start_meta(artifacts_dir)
    except (OSError, MonitorError):
        meta = {}
    monitor_id = str(meta.get("monitor_id") or "")
    state = str(meta.get("monitor_state") or "")
    if state == "running":
        return _StagedMonitorCleanupResult(
            monitor_id=monitor_id,
            staged_id=staged_id or str(meta.get("monitor_staged_id") or "") or None,
            held=held,
            released_join=False,
            settled_tool_run_id=None,
            member_state=state,
            released_prepared_intent=False,
            skipped=True,
        )
    payload = _load_payload_optional(artifacts_dir)
    claim = claim_context(payload) if payload is not None else {}
    staged = (
        staged_id
        or str(meta.get("monitor_staged_id") or "")
        or str((payload or {}).get("staged_id") or "")
        or None
    )
    mode = join_mode or str(claim.get("join_mode") or "none")
    run_id = tool_run_id or str(claim.get("tool_run_id") or "") or None
    if run_id is None:
        resources = (payload or {}).get("resources")
        if isinstance(resources, dict):
            raw = resources.get("tool_run_id")
            run_id = str(raw) if raw else None
    joined = tool_run_joined or bool(claim.get("tool_run_joined"))
    released_join = False
    settled_id: str | None = None
    if mode == "staged" and run_id and staged:
        released_join = _release_staged_join(run_id, staged, monitor_id)
    elif run_id and not joined and mode != "ordinary":
        if _settle_unstarted_run(run_id, held=held):
            settled_id = run_id
    if monitor_id:
        clear_staged_owner_index(monitor_id)
    starter = starter_artifacts_dir or str(claim.get("starter_artifacts_dir") or "")
    if not starter and payload is not None:
        starter_block = payload.get("starter")
        if isinstance(starter_block, dict):
            starter = str(starter_block.get("artifacts_dir") or "")
    prepared_ref = prepared_intent_ref or shared_prepared_intent_ref(payload or {})
    if prepared_ref is None:
        prepared_ref = optional_str(claim.get("completion_ref"))
    released_prepared = False
    if prepared_ref and staged and monitor_id and starter:
        from sase.finalizers.prepare import rollback_prepared_completion
        from sase.finalizers._prepare_reservations import release_prepared_intent

        # A pre-ack bind is reusable after rollback. Both operations use the
        # persisted starter store, which is also the reservation's owner.
        rollback_prepared_completion(
            prepared_ref,
            monitor_id=monitor_id,
            artifacts_dir=starter,
        )
        try:
            released_prepared = release_prepared_intent(
                prepared_ref,
                staged_id=staged,
                monitor_id=monitor_id,
                artifacts_dir=starter,
            )
        except Exception:  # noqa: BLE001 - cleanup remains best effort.
            released_prepared = False
    if held:
        from sase.axe.run_agent_helpers_artifacts import update_meta_field

        if monitor_id:
            update_meta_field(artifacts_dir, "monitor_stage_held", True)
        return _StagedMonitorCleanupResult(
            monitor_id=monitor_id,
            staged_id=staged,
            held=True,
            released_join=released_join,
            settled_tool_run_id=settled_id,
            member_state=state or "staged",
            released_prepared_intent=released_prepared,
        )
    if starter:
        discard_staged_handoff(starter)
    if monitor_id:
        teardown_failed_member(artifacts_dir, "staged monitor discarded")
    return _StagedMonitorCleanupResult(
        monitor_id=monitor_id,
        staged_id=staged,
        held=False,
        released_join=released_join,
        settled_tool_run_id=settled_id,
        member_state="failed",
        released_prepared_intent=released_prepared,
    )


def _load_payload_optional(artifacts_dir: str) -> dict[str, Any] | None:
    path = launch_payload_path(artifacts_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _release_staged_join(run_id: str, staged_id: str, monitor_id: str) -> bool:
    from sase.core.tool_run import tool_run_release_staged_join

    try:
        tool_run_release_staged_join(
            {
                "schema_version": 1,
                "run_id": run_id,
                "staged_id": staged_id,
                "monitor_id": monitor_id,
            }
        )
    except Exception:  # noqa: BLE001 - cleanup is best effort and idempotent.
        return False
    return True


def _settle_unstarted_run(run_id: str, *, held: bool) -> bool:
    from sase.tool.executor_recording import finish_tool_run

    reason = (
        "staged monitor held; command was not run"
        if held
        else "staged monitor discarded; command was not run"
    )
    # A reserved run that never started settles as stop_requested.
    return finish_tool_run(
        run_id,
        state="signaled",
        exit_code=None,
        duration_ms=0,
        terminal_cause="stop_requested",
        diagnostics=["command was not run", reason],
    )


__all__ = [
    "cleanup_staged_monitor",
]
