"""Durable monitor settlement for Agent Hijack custody."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.hijack._stop_models import HijackTarget, StopDeps
from sase.monitor.settlement_fresh_owner import monitor_owner_timestamp


@dataclass(frozen=True, slots=True)
class _MonitorHijackDisposition:
    """Result of observing a monitor hijack at its settlement boundary."""

    handled: bool
    settled: bool = False
    hijack_id: str | None = None
    error: str | None = None


def monitor_hijack_pending(artifacts_dir: str, meta: dict[str, Any]) -> bool:
    """Return whether normal monitor progression must stop for a hijack."""
    from sase.agent._user_kill_intent import has_hijack_intent
    from sase.agent.hijack import ledger

    if has_hijack_intent(artifacts_dir):
        return True
    record = ledger.load_record_by_artifacts_dir(artifacts_dir)
    return bool(
        isinstance(record, dict)
        and record.get("scope") == "monitor"
        and record.get("state") in {"latched", "stopping", "held"}
    )


def settle_monitor_hijack(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    monitor_state: str,
    project_name: str | None,
) -> _MonitorHijackDisposition:
    """Apply a matching monitor intent/latch before any ordinary settlement."""
    from sase.agent._user_kill_intent import (
        has_hijack_intent,
        hijack_intent_custody_pid,
        hijack_intent_id,
    )
    from sase.agent.hijack import ledger

    intent_present = has_hijack_intent(artifacts_dir)
    hijack_id = hijack_intent_id(artifacts_dir) if intent_present else None
    record = ledger.load_record(hijack_id) if hijack_id else None
    if record is None:
        record = ledger.load_record_by_artifacts_dir(artifacts_dir)
    if not intent_present and not (
        isinstance(record, dict)
        and record.get("scope") == "monitor"
        and record.get("state") in {"latched", "stopping", "held"}
    ):
        return _MonitorHijackDisposition(handled=False)

    if not isinstance(record, dict):
        return _MonitorHijackDisposition(
            handled=True,
            hijack_id=hijack_id,
            error="monitor hijack intent has no durable ledger record; custody retained",
        )
    hijack_id = str(record.get("hijack_id") or "")
    if (
        not hijack_id
        or record.get("scope") != "monitor"
        or str(record.get("artifacts_dir") or "") != artifacts_dir
    ):
        return _MonitorHijackDisposition(
            handled=True,
            hijack_id=hijack_id or None,
            error="monitor hijack identity does not match this artifacts generation",
        )
    # The orchestrator records intent before it pins the claim and advances
    # requested -> stopping. If the monitor reaches its terminal callback in
    # that small window, let normal settlement finish so the command can win
    # the race cleanly. Once stopping is durable, the intent owns settlement.
    if intent_present and record.get("state") == "requested":
        return _MonitorHijackDisposition(handled=False, hijack_id=hijack_id)
    if monitor_state == "running":
        return _pending(record, "monitor command has not reached a terminal state")

    target, claim, project_file = _monitor_hijack_target(
        artifacts_dir, meta, project_name, record
    )
    if target is None or claim is None:
        return _pending(
            record, project_file or "exact numbered workspace claim is unavailable"
        )
    if project_file is None:
        return _pending(record, "the monitor project file is unavailable")

    descriptor_path = _write_recovery_descriptor(
        artifacts_dir,
        meta,
        record,
        target,
        monitor_state=monitor_state,
    )
    if descriptor_path is None:
        return _pending(record, "monitor recovery descriptor could not be persisted")

    custody_pid = hijack_intent_custody_pid(artifacts_dir)
    if custody_pid is None and record.get("state") == "latched":
        # Latches are requested at a settlement boundary rather than through
        # the immediate-stop intent file. The process applying that boundary
        # becomes the exact temporary claim owner while the record is pinned.
        custody_pid = os.getpid()
    if record.get("state") != "held":
        transfer_error = _transfer_exact_claim(
            target,
            claim,
            custody_pid=custody_pid,
            hijack_id=hijack_id,
        )
        if transfer_error:
            return _pending(record, transfer_error)
        try:
            from sase.agent.hijack._stop_claim import pin_claim

            if not pin_claim(target):
                return _pending(
                    record,
                    "the exact transferred monitor claim could not be pinned",
                )
        except Exception as exc:  # noqa: BLE001 - custody must remain repairable.
            return _pending(record, f"could not pin monitor claim: {exc}")

    suppressed = {"kind": "monitor_followup", "ref": str(descriptor_path)}
    try:
        ledger.merge_record_fields(
            hijack_id,
            {
                "expected_claim_owner_pid": target.claim_pid,
                "boundary": "monitor",
                "boundary_outcome": monitor_state,
                "suppressed_followup": suppressed,
                "error": None,
            },
        )
        record = ledger.load_record(hijack_id) or record
        if record.get("state") == "latched":
            from sase.agent.hijack._latch_common import owner_identity_for, same_owner

            identity = owner_identity_for(target)
            if not same_owner(
                record,
                target,
                identity,
                target_key=str(record.get("target_key") or ""),
            ):
                return _pending(
                    record, "monitor latch owner identity changed at settlement"
                )
            record = ledger.cas_advance_record(
                record,
                {
                    "event": "apply_latch",
                    "boundary": "monitor",
                    "boundary_outcome": monitor_state,
                    "suppressed_followup": suppressed,
                },
            )
        elif record.get("state") == "requested":
            record = ledger.cas_advance_record(record, {"event": "begin_stop"})
        elif record.get("state") == "stop_blocked":
            record = ledger.cas_advance_record(record, {"event": "retry_stop"})
        if record.get("state") != "stopping":
            if record.get("state") == "held":
                _write_hijacked_markers(
                    artifacts_dir,
                    meta,
                    record,
                    monitor_state=monitor_state,
                    descriptor_path=descriptor_path,
                    project_file=project_file,
                )
                return _MonitorHijackDisposition(
                    handled=True, settled=True, hijack_id=hijack_id
                )
            return _pending(record, f"unexpected ledger state {record.get('state')!r}")

        from sase.agent.hijack._stop_evidence import collect_and_attach_evidence

        evidence_record, evidence_error, snapshot_error = collect_and_attach_evidence(
            hijack_id, target, deps=StopDeps()
        )
        record = evidence_record or ledger.load_record(hijack_id) or record
        if snapshot_error:
            return _pending(
                record, f"monitor workspace snapshot is pending: {snapshot_error}"
            )
        _write_hijacked_markers(
            artifacts_dir,
            meta,
            record,
            monitor_state=monitor_state,
            descriptor_path=descriptor_path,
            project_file=project_file,
        )
        if evidence_error:
            ledger.merge_record_fields(hijack_id, {"error": evidence_error})
        held = ledger.cas_advance_record(
            ledger.load_record(hijack_id) or record,
            {"event": "confirmed_stop"},
        )
        if evidence_error:
            ledger.merge_record_fields(hijack_id, {"error": evidence_error})
            return _MonitorHijackDisposition(
                handled=True,
                settled=True,
                hijack_id=hijack_id,
                error=evidence_error,
            )
        return _MonitorHijackDisposition(
            handled=True, settled=held.get("state") == "held", hijack_id=hijack_id
        )
    except Exception as exc:  # noqa: BLE001 - intent suppresses normal release.
        return _pending(record, str(exc))


def _monitor_hijack_target(
    artifacts_dir: str,
    meta: dict[str, Any],
    project_name: str | None,
    record: dict[str, Any],
) -> tuple[HijackTarget | None, Any | None, str | None]:
    from sase.running_field import get_claimed_workspaces
    from sase.workflows.utils import get_project_file_path
    from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW

    project = project_name or _optional_str(meta.get("project_name"))
    project_file = _optional_str(meta.get("project_file"))
    if project_file is None and project:
        try:
            project_file = get_project_file_path(project)
        except Exception:
            project_file = None
    workspace_num = meta.get("workspace_num")
    if (
        project_file is None
        or isinstance(workspace_num, bool)
        or not isinstance(workspace_num, int)
        or workspace_num <= 0
    ):
        return None, None, "monitor hijack requires an exact numbered workspace claim"
    timestamp = monitor_owner_timestamp(artifacts_dir)
    if not timestamp:
        return None, None, "monitor artifacts generation is unavailable"
    name = _optional_str(meta.get("name")) or str(record.get("agent_name") or "")
    expected_pid = record.get("expected_claim_owner_pid")
    if isinstance(expected_pid, bool) or not isinstance(expected_pid, int):
        expected_pid = meta.get("pid")
    if isinstance(expected_pid, bool) or not isinstance(expected_pid, int):
        return None, None, "monitor supervisor PID is unavailable"
    cl_name = _optional_str(meta.get("cl_name")) or _optional_str(
        meta.get("patch_name")
    )
    claims = get_claimed_workspaces(project_file)
    claim = next(
        (
            item
            for item in claims
            if item.workspace_num == workspace_num
            and item.artifacts_timestamp == timestamp
            and item.pid == expected_pid
            and item.cl_name == cl_name
            and item.workflow == MONITOR_WORKSPACE_CLAIM_WORKFLOW
        ),
        None,
    )
    custody_pid = record.get("expected_claim_owner_pid")
    if (
        claim is None
        and isinstance(custody_pid, int)
        and not isinstance(custody_pid, bool)
    ):
        claim = next(
            (
                item
                for item in claims
                if item.workspace_num == workspace_num
                and item.artifacts_timestamp == timestamp
                and item.pid == custody_pid
                and item.cl_name == cl_name
                and item.workflow == MONITOR_WORKSPACE_CLAIM_WORKFLOW
            ),
            None,
        )
    if claim is None:
        return None, None, "monitor claim owner or artifacts generation changed"
    from sase.agent.hijack._stop_models import read_done_marker

    done_outcome, done_recovery = read_done_marker(artifacts_dir)
    target = HijackTarget(
        name=name,
        artifacts_dir=artifacts_dir,
        project_name=project or "",
        project_file=project_file,
        artifacts_timestamp=timestamp,
        is_home=False,
        pid=_valid_pid(meta.get("pid")) or _valid_pid(record.get("pid")),
        claim_pid=int(claim.pid),
        claim_pinned=bool(claim.pinned),
        cl_name=claim.cl_name,
        workflow=claim.workflow,
        workspace_num=workspace_num,
        workspace_dir=_optional_str(meta.get("workspace_dir")),
        status="DONE",
        lifecycle_phase=_optional_str(meta.get("lifecycle_phase")),
        is_monitor_turn=True,
        is_gate_turn=False,
        gate_state=None,
        agent_session=_optional_str(meta.get("agent_session")),
        capabilities=[],
        model_alias=_optional_str(meta.get("model_alias")),
        model_alias_trail=[],
        model_origin=_optional_str(meta.get("model_origin")),
        provider=_optional_str(meta.get("llm_provider")),
        model=_optional_str(meta.get("model")),
        effort=_optional_str(meta.get("reasoning_effort")),
        run_started_at=None,
        done_outcome=done_outcome,
        done_recovery=done_recovery,
        monitor_id=_optional_str(meta.get("monitor_id")),
        monitor_supervisor_identity=_optional_str(
            meta.get("monitor_supervisor_identity")
        ),
    )
    return target, claim, project_file


def _transfer_exact_claim(
    target: HijackTarget,
    claim: Any,
    *,
    custody_pid: int | None,
    hijack_id: str,
) -> str | None:
    if custody_pid is None:
        return "the monitor hijack intent has no recorded custody process"
    if custody_pid == claim.pid:
        target.claim_pid = custody_pid
        target.claim_pinned = bool(claim.pinned)
        return None
    from sase.running_field import get_claimed_workspaces, transfer_workspace_claim

    moved = transfer_workspace_claim(
        target.project_file,
        int(target.workspace_num or 0),
        from_pid=int(claim.pid),
        to_pid=custody_pid,
        new_workflow=claim.workflow,
        new_artifacts_timestamp=target.artifacts_timestamp,
        cl_name=claim.cl_name,
        caller_tag="agent_hijack_monitor",
        expected_from=claim,
    )
    if not moved.success:
        return moved.error or "the exact monitor workspace claim could not be re-owned"
    updated = next(
        (
            item
            for item in get_claimed_workspaces(target.project_file)
            if item.workspace_num == target.workspace_num
            and item.pid == custody_pid
            and item.workflow == claim.workflow
            and item.cl_name == claim.cl_name
            and item.artifacts_timestamp == target.artifacts_timestamp
        ),
        None,
    )
    if updated is None:
        return "claim transfer completed but exact custodian ownership could not be verified"
    target.claim_pid = custody_pid
    target.claim_pinned = bool(updated.pinned)
    from sase.agent.hijack import ledger

    ledger.merge_record_fields(hijack_id, {"expected_claim_owner_pid": custody_pid})
    return None


def _write_recovery_descriptor(
    artifacts_dir: str,
    meta: dict[str, Any],
    record: dict[str, Any],
    target: HijackTarget,
    *,
    monitor_state: str,
) -> Path | None:
    hijack_id = str(record.get("hijack_id") or "")
    if not hijack_id:
        return None
    safe_id = "".join(
        char if char.isalnum() or char in "-_" else "_" for char in hijack_id
    )
    directory = Path(artifacts_dir) / "hijack_recovery"
    path = directory / f"{safe_id}.json"
    followup_fields = (
        "monitor_next_action",
        "monitor_next_model",
        "monitor_next_output",
        "monitor_completion_ref",
        "monitor_outcome_policy_digest",
        "monitor_outcome_policy_path",
        "continuation_intent_ref",
        "continuation_checkpoint_ref",
        "continuation_monitor_result_id",
        "continuation_monitor_result_ref",
        "continuation_monitor_result_path",
        "continuation_monitor_result_sha256",
        "continuation_monitor_result_node_ref",
        "continuation_monitor_result_manifest_ref",
        "continuation_monitor_result_manifest_path",
        "continuation_node_ref",
        "continuation_manifest_ref",
        "continuation_manifest_path",
        "continuation_capture_disposition",
        "monitor_host_completion_status",
        "monitor_host_completion_message",
        "monitor_host_completion_reason",
        "monitor_host_completion_reasons",
        "monitor_tool_run_id",
        "monitor_tool_run_joined",
        "monitor_starter_agent",
        "agent_session",
        "bead_id",
        "phase_bead_id",
    )
    payload = {
        "schema_version": 1,
        "hijack_id": hijack_id,
        "monitor_id": target.monitor_id,
        "member_name": target.name,
        "artifacts_dir": artifacts_dir,
        "artifacts_timestamp": target.artifacts_timestamp,
        "project_file": target.project_file,
        "project_name": target.project_name,
        "workspace_num": target.workspace_num,
        "workspace_dir": target.workspace_dir,
        "claim_owner_pid": record.get("expected_claim_owner_pid"),
        "custody_pid": _optional_int_from_intent(artifacts_dir),
        "command": meta.get("monitor_command"),
        "execution_argv": meta.get("monitor_execution_argv"),
        "cwd": meta.get("monitor_cwd") or meta.get("cwd"),
        "timeout_seconds": meta.get("monitor_timeout_seconds"),
        "idle_timeout_seconds": meta.get("monitor_idle_timeout_seconds"),
        "output_policy": meta.get("monitor_next_output"),
        "followup": {key: meta[key] for key in followup_fields if key in meta},
        "command_result": {
            "state": monitor_state,
            "exit_code": meta.get("monitor_exit_code"),
            "elapsed_seconds": meta.get("monitor_elapsed_seconds"),
            "timeout_kind": meta.get("monitor_timeout_kind"),
            "timeout_message": meta.get("monitor_timeout_message"),
            "error": meta.get("monitor_error"),
            "stopped_at": meta.get("stopped_at"),
        },
        "output_locators": {
            key: meta.get(key)
            for key in (
                "monitor_output_path",
                "monitor_retained_log_metadata_path",
                "monitor_retained_log_ref",
                "monitor_diagnostic_manifest_path",
                "monitor_diagnostic_manifest_ref",
                "continuation_monitor_result_path",
                "continuation_monitor_result_ref",
                "response_path",
                "monitor_response_path",
            )
            if meta.get(key)
        },
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            dir=directory, prefix=f".{safe_id}.", suffix=".tmp"
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary_path, path)
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return path
        finally:
            temporary_path.unlink(missing_ok=True)
    except FileExistsError:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if (
            isinstance(existing, dict)
            and existing.get("hijack_id") == hijack_id
            and existing.get("artifacts_dir") == artifacts_dir
            and existing.get("monitor_id") == target.monitor_id
        ):
            return path
        return None
    except OSError:
        return None


def _write_hijacked_markers(
    artifacts_dir: str,
    meta: dict[str, Any],
    record: dict[str, Any],
    *,
    monitor_state: str,
    descriptor_path: Path,
    project_file: str,
) -> None:
    from sase.axe.agent_meta import write_agent_meta_atomic
    from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
    from sase.agent._user_kill_intent import pending_hijack_recovery

    hijack_id = str(record.get("hijack_id") or "")
    meta.update(
        {
            "monitor_state": monitor_state,
            "monitor_settled": True,
            "monitor_hijack_id": hijack_id,
            "monitor_hijack_recovery_ref": str(descriptor_path),
            "monitor_hijack_boundary_outcome": monitor_state,
            "monitor_hijack_state": "held",
            "monitor_followup_outcome": "hijacked",
            "monitor_followup_error": None,
        }
    )
    done_path = Path(artifacts_dir) / "done.json"
    try:
        existing = json.loads(done_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        existing = {}
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"existing monitor done marker could not be read: {exc}"
        ) from exc
    if not isinstance(existing, dict):
        raise RuntimeError("existing monitor done marker is not an object")
    if existing.get("project_file") not in (None, project_file):
        raise RuntimeError("existing done marker belongs to a different project")
    if existing.get("name") not in (None, meta.get("name")):
        raise RuntimeError("existing done marker belongs to a different member")
    if existing.get("artifacts_timestamp") not in (
        None,
        monitor_owner_timestamp(artifacts_dir),
    ):
        raise RuntimeError(
            "existing done marker belongs to a different artifacts generation"
        )
    if existing.get("outcome") not in (None, "monitored", "hijacked"):
        raise RuntimeError(
            "existing done marker contains a conflicting terminal outcome"
        )
    write_agent_meta_atomic(artifacts_dir, meta)
    if existing.get("outcome") == "hijacked":
        recovery = existing.get("recovery")
        if isinstance(recovery, dict) and recovery.get("hijack_id") == hijack_id:
            return
    marker = dict(existing)
    marker.update(
        {
            "outcome": "hijacked",
            "name": meta.get("name"),
            "cl_name": meta.get("cl_name"),
            "project_file": project_file,
            "artifacts_timestamp": monitor_owner_timestamp(artifacts_dir),
            "workspace_dir": meta.get("workspace_dir"),
            "workspace_num": meta.get("workspace_num"),
            "monitor_id": meta.get("monitor_id"),
            "monitor_state": monitor_state,
            "monitor_exit_code": meta.get("monitor_exit_code"),
            "monitor_elapsed_seconds": meta.get("monitor_elapsed_seconds"),
            "monitor_timeout_kind": meta.get("monitor_timeout_kind"),
            "monitor_timeout_message": meta.get("monitor_timeout_message"),
            "monitor_followup_outcome": "hijacked",
            "monitor_hijack_id": hijack_id,
            "monitor_hijack_recovery_ref": str(descriptor_path),
            "boundary_outcome": monitor_state,
            "status_label": "Stopped",
            "status_bucket": "Stopped",
            "recovery": pending_hijack_recovery(artifacts_dir),
        }
    )
    marker["recovery"]["hijack_id"] = hijack_id
    marker.update(
        {
            key: meta[key]
            for key in (
                "monitor_diagnostic_manifest_path",
                "monitor_diagnostic_manifest_ref",
                "monitor_retained_log_metadata_path",
                "monitor_retained_log_ref",
                "continuation_monitor_result_id",
                "continuation_monitor_result_ref",
                "continuation_monitor_result_path",
                "continuation_monitor_result_sha256",
                "continuation_monitor_result_node_ref",
                "continuation_monitor_result_manifest_ref",
                "continuation_monitor_result_manifest_path",
            )
            if meta.get(key)
        }
    )
    from sase.turns.settlement import stamp_turn_finished_at

    stamp_turn_finished_at(marker)
    write_done_marker_and_update_index(artifacts_dir, marker)


def _pending(record: dict[str, Any], error: str) -> _MonitorHijackDisposition:
    from sase.agent.hijack import ledger

    hijack_id = str(record.get("hijack_id") or "")
    if hijack_id:
        ledger.merge_record_fields(hijack_id, {"error": error})
    return _MonitorHijackDisposition(
        handled=True,
        settled=False,
        hijack_id=hijack_id or None,
        error=error,
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _valid_pid(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 1
        else None
    )


def _optional_int_from_intent(artifacts_dir: str) -> int | None:
    from sase.agent._user_kill_intent import hijack_intent_custody_pid

    return hijack_intent_custody_pid(artifacts_dir)


__all__ = [
    "monitor_hijack_pending",
    "settle_monitor_hijack",
]
