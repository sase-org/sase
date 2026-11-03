"""The ordered stop protocol for Agent Hijack (phase ``stop``).

Stopping a stalled agent without losing its work follows a fixed order:

1. **Eligibility.** Gather facts (row, meta, pid identity, claim, lifecycle
   phase, capability) and call the Rust eligibility function. A refusal
   returns exit 2 and changes nothing.
2. **Record and intent.** Exclusively create the ledger record (``requested``)
   and write the hijack-mode user-kill intent. Both exist before any signal.
3. **Pin.** Pin the workspace claim under the claim lock, recording the prior
   pin state. A mismatched or replaced claim aborts.
4. **Lost race.** If ``done.json`` already holds a real outcome, the record
   becomes ``finished_first``, the intent is removed, and the pin is restored
   only if this hijack set it.
5. **Stop.** The record moves to ``stopping`` and the verified terminator runs
   (process-identity checks, 6 s grace, then SIGKILL). No ``killpg`` shortcut.
6. **Survivors.** Any surviving process moves the record to ``stop_failed``,
   removes the intent, and restores the pin. The row stays RUNNING. Exit 1.
7. **Fallback.** When the runner died before settling, the orchestrator writes
   the same ``done.json`` the runner would have and re-asserts the pin.
8. **Evidence**, best-effort and off the TUI: per-repo diff stats, the last
   tool call and its age, the run duration, and stale ``index.lock`` files.
9. **Strict snapshot.** Every repo with changes is snapshotted. A failure is
   recorded but does not block ``held``; every later release must snapshot
   first.
10. **Publish.** The record moves to ``held`` and HIJACKED is published.

Only steps 1--7 run before the process tree is dead; evidence and snapshots
are deliberately last so they observe the final state.
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Callable

LOG = logging.getLogger(__name__)

#: Grace period for the verified tree terminator (the existing 6 s default).
STOP_GRACE_SECONDS = 6.0

#: Source tag recorded in the user-kill intent marker.
STOP_INTENT_SOURCE = "agent_hijack"

_EXIT_HELD = 0
_EXIT_REFUSED = 2
_EXIT_FAILED = 1


@dataclass
class _HijackTarget:
    """Resolved facts about the agent row about to be hijacked."""

    name: str
    artifacts_dir: str
    project_name: str
    project_file: str
    artifacts_timestamp: str
    is_home: bool
    pid: int | None
    claim_pid: int | None
    claim_pinned: bool
    cl_name: str | None
    workflow: str | None
    workspace_num: int | None
    workspace_dir: str | None
    status: str
    lifecycle_phase: str | None
    is_monitor_turn: bool
    is_gate_turn: bool
    agent_session: str | None
    capabilities: list[str]
    model_alias: str | None
    model_alias_trail: list[str]
    model_origin: str | None
    provider: str | None
    model: str | None
    effort: str | None
    run_started_at: float | None
    done_outcome: str | None
    done_recovery: dict[str, Any] | None


@dataclass
class HijackStopResult:
    """Outcome of one stop-orchestrator run."""

    status: str
    message: str
    exit_code: int
    hijack_id: str | None = None
    record: dict[str, Any] | None = None
    reason: str | None = None


@dataclass
class _StopDeps:
    """Seams for tests; production uses the defaults."""

    find_agent: Callable[[str], Any | None] | None = None
    list_running: Callable[[], list[Any]] | None = None
    terminate: Callable[..., Any] | None = None
    snapshot_repo: Callable[..., Any] | None = None
    now: Callable[[], float] | None = None


def _hijack_stop_enabled() -> bool:
    """Return whether hijack ingress is enabled by the beta flag."""
    from sase.feature_flags import FeatureFlag, current_flags

    try:
        return bool(current_flags().enabled(FeatureFlag.agent_hijack))
    except Exception:
        return False


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
    deps: _StopDeps | None = None,
) -> HijackStopResult:
    """Run the ordered stop orchestrator for *name*.

    Exit codes follow the CLI contract: 0 means HIJACKED, 2 means refused
    with nothing changed, and 1 means stop failed or an error occurred.
    """
    deps = deps or _StopDeps()
    if not _hijack_stop_enabled():
        return HijackStopResult(
            status="refused",
            message=(
                "Agent hijack is disabled; enable the agent_hijack flag to use "
                "`sase agent hijack`. Already-hijacked agents stay recoverable."
            ),
            exit_code=_EXIT_REFUSED,
            reason="flag_disabled",
        )
    target = _resolve_target(name, deps=deps)
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
        pin = _pin_claim(target)
        if not pin:
            _abort_before_stop(
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
        _abort_before_stop(target, resolved_id, reason=str(exc))
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
        _remove_intent(target.artifacts_dir)
        if pinned_by_us:
            _unpin_claim(target)
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

    termination = _terminate_tree(target, deps=deps)
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
        _remove_intent(target.artifacts_dir)
        if pinned_by_us:
            _unpin_claim(target)
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

    _ensure_hijacked_settlement(target, resolved_id, pinned_by_us)
    try:
        record = ledger.load_record(resolved_id) or record
    except Exception:
        pass
    evidence_error: str | None = None
    try:
        evidence = _collect_evidence(target, deps=deps)
        _attach_evidence(resolved_id, evidence)
        record = ledger.load_record(resolved_id) or record
    except Exception as exc:  # noqa: BLE001 - evidence is best-effort.
        evidence_error = str(exc)
        LOG.warning("hijack evidence collection failed: %s", exc)
    try:
        snapshots, snapshot_error = _capture_snapshots(target, deps=deps)
        if snapshots:
            _attach_evidence(resolved_id, {"snapshots": snapshots})
        if snapshot_error and not evidence_error:
            evidence_error = snapshot_error
        if snapshot_error:
            _attach_evidence(
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
    summary = _format_diff_summary(held)
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


def _resolve_target(name: str, *, deps: _StopDeps) -> _HijackTarget | None:
    find_agent = deps.find_agent or _default_find_agent
    found = find_agent(name)
    if found is None:
        return None
    artifacts_dir = str(
        getattr(found, "artifacts_dir", "") or "",
    )
    if not artifacts_dir:
        return None
    from sase.agent.running import (
        named_agent_project_fields as _project_fields,
    )

    _, project_name, project_file, timestamp, is_home = _project_fields(found)
    meta = _read_json_dict(Path(artifacts_dir) / "agent_meta.json") or {}
    row = _find_live_row(name, deps=deps)
    claim = _find_claim(project_file, timestamp) if not is_home else None
    claim_pid = int(claim.pid) if claim is not None else None
    meta_pid = _valid_pid(meta.get("pid"))
    pid = claim_pid or meta_pid
    if pid is None and row is not None:
        pid = _valid_pid(getattr(row, "pid", None))
    workspace_num = (
        int(claim.workspace_num) if claim is not None else _valid_workspace(row)
    )
    workspace_dir = _row_workspace_dir(row) or _meta_workspace_dir(meta)
    if workspace_dir is None and claim is not None:
        workspace_dir = _claim_workspace_dir(project_name, claim)
    status = _row_status(row, artifacts_dir, pid)
    capabilities = meta.get("runner_capabilities")
    capability_list = (
        [str(item) for item in capabilities] if isinstance(capabilities, list) else []
    )
    finalizer = meta.get("finalizer_status")
    phase = None
    if isinstance(finalizer, dict):
        raw_phase = finalizer.get("phase")
        if isinstance(raw_phase, str) and raw_phase:
            phase = raw_phase
    done_outcome, done_recovery = _read_done_marker(artifacts_dir)
    trail = meta.get("model_alias_trail")
    return _HijackTarget(
        name=str(getattr(found, "name", name) or name),
        artifacts_dir=artifacts_dir,
        project_name=project_name,
        project_file=project_file,
        artifacts_timestamp=timestamp,
        is_home=is_home,
        pid=pid,
        claim_pid=claim_pid,
        claim_pinned=bool(getattr(claim, "pinned", False)),
        cl_name=(claim.cl_name if claim is not None else None)
        or _meta_str(meta, "patch_name", "cl_name", "changespec_name"),
        workflow=claim.workflow if claim is not None else None,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        status=status,
        lifecycle_phase=phase,
        is_monitor_turn=bool(getattr(row, "is_monitor", False))
        if row is not None
        else False,
        is_gate_turn=_meta_bool(meta, "gate_turn", "is_gate_turn"),
        agent_session=getattr(row, "agent_session", None),
        capabilities=capability_list,
        model_alias=_meta_str(meta, "model_alias"),
        model_alias_trail=[str(item) for item in trail]
        if isinstance(trail, list)
        else [],
        model_origin=_meta_str(meta, "prompt_origin", "model_origin"),
        provider=_meta_str(meta, "agent_llm_provider", "provider"),
        model=_meta_str(meta, "agent_model", "model"),
        effort=_meta_str(meta, "agent_effort", "effort"),
        run_started_at=_meta_float(meta, "booted_at", "started_at"),
        done_outcome=done_outcome,
        done_recovery=done_recovery,
    )


def _default_find_agent(name: str) -> Any | None:
    from sase.agent.names import find_named_agent

    return find_named_agent(name)


def _find_live_row(name: str, *, deps: _StopDeps) -> Any | None:
    list_running = deps.list_running
    if list_running is None:
        try:
            from sase.agent.running_listing import list_running_agents

            list_running = list_running_agents
        except Exception:
            return None
    try:
        rows = list_running()
    except Exception:
        return None
    for row in rows or ():
        if getattr(row, "name", None) == name and getattr(row, "artifacts_dir", None):
            return row
    return None


def _find_claim(project_file: str, timestamp: str) -> Any | None:
    try:
        from sase.running_field import get_claimed_workspaces

        for claim in get_claimed_workspaces(project_file):
            if claim.artifacts_timestamp == timestamp:
                return claim
    except Exception:
        return None
    return None


def _valid_pid(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 1 else None


def _valid_workspace(row: Any | None) -> int | None:
    if row is None:
        return None
    value = getattr(row, "workspace_num", None)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _row_workspace_dir(row: Any | None) -> str | None:
    if row is None:
        return None
    value = getattr(row, "workspace_dir", None)
    return value if isinstance(value, str) and value else None


def _meta_workspace_dir(meta: dict[str, Any]) -> str | None:
    for key in ("workspace_dir", "workspace_root", "cwd"):
        value = meta.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _claim_workspace_dir(project_name: str, claim: Any) -> str | None:
    try:
        from sase.running_field._workspace import get_workspace_directory_for_num

        directory, _ = get_workspace_directory_for_num(
            int(claim.workspace_num), project_name, clean=False
        )
        return directory
    except Exception:
        return None


def _row_status(row: Any | None, artifacts_dir: str, pid: int | None) -> str:
    if row is not None:
        status = str(getattr(row, "status", "") or "").upper()
        if status:
            return status
    if pid is not None:
        try:
            from sase.agent.process_tree import process_is_running

            if process_is_running(pid):
                return "RUNNING"
        except Exception:
            pass
    return "DONE"


def _meta_str(meta: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _meta_bool(meta: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, bool):
            return value
    return False


def _meta_float(meta: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_done_marker(artifacts_dir: str) -> tuple[str | None, dict[str, Any] | None]:
    data = _read_json_dict(Path(artifacts_dir) / "done.json")
    if data is None:
        return None, None
    outcome = data.get("outcome")
    recovery = data.get("recovery")
    return (
        outcome if isinstance(outcome, str) else None,
        dict(recovery) if isinstance(recovery, dict) else None,
    )


def _read_done_outcome(artifacts_dir: str) -> str | None:
    outcome, _ = _read_done_marker(artifacts_dir)
    return outcome


def _check_eligibility(target: _HijackTarget) -> dict[str, Any]:
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


def _pin_claim(target: _HijackTarget) -> bool:
    from sase.running_field._hold import hold_workspace_claim

    assert target.workspace_num is not None
    result = hold_workspace_claim(
        target.project_file,
        int(target.workspace_num),
        target.workflow or "",
        target.cl_name or "",
        target.artifacts_timestamp,
        caller_tag="agent_hijack",
        expected_pid=target.claim_pid,
    )
    return bool(result.success)


def _unpin_claim(target: _HijackTarget) -> None:
    """Restore the pin this hijack set back to unpinned.

    Mirrors :mod:`sase.running_field._hold` under the same project lock:
    the matching RUNNING row is rewritten in place with ``PINNED`` removed.
    Only call when this hijack set the pin.
    """
    from sase.ace.patch import patch_lock, write_patch_atomic
    from sase.logs.workspace_claim_ledger import record_running_field_mutation
    from sase.running_field._model import WorkspaceClaim

    if target.workspace_num is None:
        return
    try:
        with patch_lock(target.project_file):
            with open(target.project_file, encoding="utf-8") as handle:
                content = handle.read()
            lines = content.splitlines(keepends=True)
            changed = False
            for index, line in enumerate(lines):
                claim = WorkspaceClaim.from_line(line)
                if (
                    claim is None
                    or claim.workspace_num != int(target.workspace_num)
                    or claim.artifacts_timestamp != target.artifacts_timestamp
                ):
                    continue
                if target.claim_pid is not None and claim.pid != int(target.claim_pid):
                    continue
                if not claim.pinned:
                    return
                suffix = tuple(part for part in claim.suffix_fields if part != "PINNED")
                lines[index] = (
                    WorkspaceClaim(
                        workspace_num=claim.workspace_num,
                        workflow=claim.workflow,
                        cl_name=claim.cl_name,
                        pid=claim.pid,
                        artifacts_timestamp=claim.artifacts_timestamp,
                        pinned=False,
                        suffix_fields=suffix,
                    ).to_line()
                    + "\n"
                )
                changed = True
                break
            if not changed:
                return
            write_patch_atomic(
                target.project_file,
                "".join(lines),
                f"Release hijack pin on workspace #{target.workspace_num}",
            )
            record_running_field_mutation(
                operation="unpin",
                project_file=target.project_file,
                workspace_num=int(target.workspace_num),
                success=True,
                before_content=content,
                after_content="".join(lines),
                workflow=target.workflow or "",
                cl_name=target.cl_name or "",
                artifacts_timestamp=target.artifacts_timestamp,
                claim_pid=target.claim_pid,
                caller_tag="agent_hijack",
            )
    except (OSError, BlockingIOError) as exc:
        LOG.warning("could not restore hijack pin: %s", exc)


def _remove_intent(artifacts_dir: str) -> None:
    try:
        Path(artifacts_dir, ".sase_user_kill_pending").unlink(missing_ok=True)
    except OSError as exc:
        LOG.warning("could not remove hijack intent: %s", exc)


def _abort_before_stop(target: _HijackTarget, hijack_id: str, reason: str) -> None:
    _remove_intent(target.artifacts_dir)
    try:
        from sase.agent.hijack import ledger

        path = ledger.hijack_record_path(hijack_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            LOG.warning("could not remove aborted hijack record: %s", exc)
    except Exception as exc:
        LOG.warning("could not remove aborted hijack record: %s", exc)
    LOG.warning("hijack %s aborted: %s", hijack_id, reason)


def _terminate_tree(target: _HijackTarget, *, deps: _StopDeps) -> Any:
    terminate = deps.terminate
    if terminate is None:
        from sase.agent.user_kill import terminate_agent_processes

        terminate = terminate_agent_processes
    assert target.pid is not None
    return terminate(
        int(target.pid),
        artifacts_dir=target.artifacts_dir,
        grace_seconds=STOP_GRACE_SECONDS,
    )


def _ensure_hijacked_settlement(
    target: _HijackTarget, hijack_id: str, pinned_by_us: bool
) -> None:
    """Write the runner-equivalent settlement when the runner cannot.

    When the runner survives SIGTERM it settles itself; when it died first
    (wedged or SIGKILLed) no ``done.json`` exists, so the orchestrator writes
    the identical ``outcome: hijacked`` marker and re-asserts the pin. The
    runner path is idempotent with this one: an existing marker is kept.
    """
    from sase.agent._user_kill_intent import pending_hijack_recovery

    done_path = Path(target.artifacts_dir) / "done.json"
    if not done_path.exists():
        from sase.axe.run_agent_exec_markers import (
            write_done_marker_and_update_index,
        )
        from sase.axe.run_agent_markers import build_done_marker

        marker = build_done_marker(
            target.cl_name or "",
            target.project_file,
            target.artifacts_timestamp,
            target.artifacts_timestamp,
            int(target.workspace_num or 0),
            target.workspace_dir or "",
            "",
            "hijacked",
            agent_name=target.name,
            recovery=pending_hijack_recovery(target.artifacts_dir),
        )
        try:
            write_done_marker_and_update_index(target.artifacts_dir, marker)
        except Exception as exc:
            LOG.warning("could not write hijacked done.json: %s", exc)
    if not target.is_home and target.workspace_num is not None and pinned_by_us:
        _pin_claim(target)


def _attach_evidence(hijack_id: str, evidence: dict[str, Any]) -> None:
    """Merge best-effort evidence fields into the record without a transition.

    Evidence is data, not state: the merge re-reads under the record lock and
    rewrites data fields at the same revision so the pending ``confirmed_stop``
    CAS still observes exactly one winner.
    """

    from sase.agent.hijack import ledger
    from sase.notification_gates.durability import atomic_write_json, file_lock

    allowed = {
        "run_duration_seconds",
        "last_tool",
        "last_tool_age_seconds",
        "repo_diffs",
        "snapshots",
        "stale_lock_files",
        "error",
    }
    payload = {key: value for key, value in evidence.items() if key in allowed}
    if not payload:
        return
    path = ledger.hijack_record_path(hijack_id)
    with file_lock(ledger.hijack_record_lock_path(hijack_id), timeout=10.0):
        current = ledger.read_hijack_record_payload(path)
        if current is None:
            raise RuntimeError(f"hijack record {hijack_id} disappeared")
        current.update(payload)
        atomic_write_json(path, current)


def _collect_evidence(target: _HijackTarget, *, deps: _StopDeps) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    now = deps.now() if deps.now is not None else time.time()
    if target.run_started_at is not None:
        evidence["run_duration_seconds"] = max(0.0, now - target.run_started_at)
    last_tool, last_tool_age = _read_last_tool(target.artifacts_dir, now=now)
    if last_tool is not None:
        evidence["last_tool"] = last_tool
    if last_tool_age is not None:
        evidence["last_tool_age_seconds"] = last_tool_age
    repo_roots = _evidence_repo_roots(target)
    diffs: list[dict[str, Any]] = []
    stale_locks: list[str] = []
    for root in repo_roots:
        stats = _git_diff_stats(root)
        if stats is not None:
            diffs.append({"repo": root, **stats})
        lock = _stale_index_lock(root)
        if lock is not None:
            stale_locks.append(lock)
    evidence["repo_diffs"] = diffs
    evidence["stale_lock_files"] = stale_locks
    return evidence


def _evidence_repo_roots(target: _HijackTarget) -> list[str]:
    roots: list[str] = []
    if target.workspace_dir:
        toplevel = _git_repo_toplevel(target.workspace_dir)
        if toplevel is not None:
            roots.append(toplevel)
    meta = _read_json_dict(Path(target.artifacts_dir) / "agent_meta.json") or {}
    for key in ("opened_repos", "linked_repos", "sidecar_repos", "repo_roots"):
        value = meta.get(key)
        if not isinstance(value, list):
            continue
        for entry in value:
            if not isinstance(entry, str) or not entry:
                continue
            toplevel = _git_repo_toplevel(entry)
            if toplevel is not None and toplevel not in roots:
                roots.append(toplevel)
    return roots


def _git_repo_toplevel(path: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    toplevel = proc.stdout.strip()
    return toplevel or None


def _git_diff_stats(root: str) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            ["git", "-C", root, "diff", "--numstat", "HEAD", "--"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    files_changed = 0
    insertions = 0
    deletions = 0
    binary_files = 0
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted = parts[0], parts[1]
        files_changed += 1
        if added == "-" or deleted == "-":
            binary_files += 1
            continue
        try:
            insertions += int(added)
            deletions += int(deleted)
        except ValueError:
            continue
    try:
        status = subprocess.run(
            ["git", "-C", root, "status", "--porcelain=v1", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        status = None
    untracked = 0
    if status is not None and status.returncode == 0:
        untracked = sum(
            1 for line in status.stdout.splitlines() if line.startswith("??")
        )
    if files_changed == 0 and untracked == 0:
        return None
    return {
        "files_changed": files_changed + untracked,
        "insertions": insertions,
        "deletions": deletions,
        "binary_files": binary_files,
    }


def _stale_index_lock(root: str) -> str | None:
    candidate = Path(root) / ".git" / "index.lock"
    try:
        if candidate.is_file():
            return str(candidate)
    except OSError:
        return None
    return None


def _read_last_tool(
    artifacts_dir: str, *, now: float
) -> tuple[str | None, float | None]:
    try:
        from sase.ace.tui.llm_calls._parser import read_tool_call_file

        entries = read_tool_call_file(
            Path(artifacts_dir) / "tool_calls.jsonl", Path(artifacts_dir), 0
        )
    except Exception:
        return None, None
    if not entries:
        return None, None
    last = entries[-1]
    name = last.tool_name or last.event or None
    age: float | None = None
    try:
        recorded = last._recorded_at_sort
        age = max(0.0, now - recorded.timestamp())
    except Exception:
        age = None
    return name, age


def _capture_snapshots(
    target: _HijackTarget, *, deps: _StopDeps
) -> tuple[list[dict[str, Any]], str | None]:
    snapshot_repo = deps.snapshot_repo
    if snapshot_repo is None:
        from sase.workspace_provider._snapshot_capture_source import (
            snapshot_git_repo as _snapshot_git_repo,
        )

        snapshot_repo = _snapshot_git_repo
    if target.workspace_dir is None or target.workspace_num is None:
        return [], None
    snapshots: list[dict[str, Any]] = []
    errors: list[str] = []
    for root in _evidence_repo_roots(target):
        try:
            record = snapshot_repo(
                root,
                workspace_dir=target.workspace_dir,
                workspace_num=int(target.workspace_num),
                label=f"hijack-{target.name}",
                reason="agent hijack",
            )
        except Exception as exc:
            errors.append(f"{root}: {exc}")
            continue
        if record is None:
            continue
        snapshots.append(
            {
                "repo": root,
                "reference": str(
                    getattr(record, "snapshot_id", "") or getattr(record, "head", "")
                ),
                "fingerprint": str(getattr(record, "worktree_tree", "")),
            }
        )
    return snapshots, "; ".join(errors) if errors else None


def _format_diff_summary(record: dict[str, Any]) -> str:
    diffs = record.get("repo_diffs")
    if not isinstance(diffs, list) or not diffs:
        return ""
    files = 0
    insertions = 0
    deletions = 0
    for entry in diffs:
        if not isinstance(entry, dict):
            continue
        try:
            files += int(entry.get("files_changed") or 0)
            insertions += int(entry.get("insertions") or 0)
            deletions += int(entry.get("deletions") or 0)
        except (TypeError, ValueError):
            continue
    if files == 0:
        return ""
    return f"{files} files +{insertions} \u2212{deletions}"


__all__ = [
    "HijackStopResult",
    "STOP_GRACE_SECONDS",
    "STOP_INTENT_SOURCE",
    "stop_agent_for_hijack",
]
