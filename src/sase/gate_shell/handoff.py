"""Host-side gate coder-handoff attempt, evidence, and recovery glue."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from sase.ace.hooks.processes import is_process_running
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.gate_followup_facade import (
    GATE_FOLLOWUP_WIRE_SCHEMA_VERSION,
    decide_gate_followup,
    gate_followup_attempt_id,
)
from sase.core.paths import sase_projects_dir
from sase.notification_gates.durability import file_lock
from sase.plan_chain import PLAN_CHAIN_CODER_SUFFIX

logger = logging.getLogger(__name__)

HandoffMode = Literal["settle", "resume", "diagnose"]

FOLLOWUP_LOCK_NAME = ".gate_followup.lock"
ATTEMPT_ID_FIELD = "gate_followup_attempt_id"
ATTEMPT_FINGERPRINT_FIELD = "gate_followup_attempt_fingerprint"
ATTEMPT_STAGE_FIELD = "gate_followup_attempt_stage"
ATTEMPT_LIVE_FIELD = "gate_followup_attempt_live"
ATTEMPT_OWNER_PID_FIELD = "gate_followup_attempt_owner_pid"
ATTEMPT_STARTED_AT_FIELD = "gate_followup_attempt_started_at"
ERROR_STAGE_FIELD = "gate_followup_error_stage"
ERROR_TYPE_FIELD = "gate_followup_error_type"
ERROR_MESSAGE_FIELD = "gate_followup_error_message"
RECONCILE_CURSOR_NAME = ".gate_handoff_reconcile.json"
RECONCILE_BATCH_SIZE = 32
FOLLOWUP_LOCK_TIMEOUT_SECONDS = 5.0


def _gate_followup_lock_path(artifacts_dir: str) -> Path:
    """Return the per-gate lock used by settlement and resume."""
    return Path(artifacts_dir) / FOLLOWUP_LOCK_NAME


def with_gate_followup_lock(artifacts_dir: str) -> Any:
    """Return the exclusive lock context for one gate's handoff."""
    return file_lock(
        _gate_followup_lock_path(artifacts_dir),
        timeout=FOLLOWUP_LOCK_TIMEOUT_SECONDS,
    )


def classify_gate_handoff(
    meta: Mapping[str, Any],
    *,
    mode: HandoffMode,
    already_settled: bool,
    followup_requested: bool,
    creator_live: bool = False,
    successor_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the Rust disposition decision for one gate snapshot."""
    fingerprint = _str(meta.get("gate_request_fingerprint")) or ""
    request: dict[str, Any] = {
        "schema_version": GATE_FOLLOWUP_WIRE_SCHEMA_VERSION,
        "mode": mode,
        "gate_id": _str(meta.get("gate_id")) or "",
        "gate_kind": _str(meta.get("gate_kind")),
        "gate_state": _str(meta.get("gate_state")) or "pending",
        "already_settled": already_settled,
        "request_fingerprint": fingerprint or None,
        "followup_requested": followup_requested,
        "creator_live": creator_live,
        "auto_suppressed": creator_live,
        "followup_outcome": _str(meta.get("gate_followup_outcome")),
        "followup_agent": _str(meta.get("gate_followup_agent")),
        "followup_error": _str(meta.get("gate_followup_error")),
        "followup_degraded_reason": _str(meta.get("gate_followup_degraded_reason")),
        "followup_prompt_path": _str(meta.get("gate_followup_prompt_path")),
        "attempt": _attempt_snapshot(meta, fingerprint),
        "successor_evidence": dict(successor_evidence or {}),
    }
    return decide_gate_followup(request)


def _attempt_snapshot(
    meta: Mapping[str, Any], fingerprint: str
) -> dict[str, Any] | None:
    """Return the persisted attempt wire, marking dead owners as not live."""
    attempt_id = _str(meta.get(ATTEMPT_ID_FIELD))
    if not attempt_id:
        return None
    owner_pid = _optional_int(meta.get(ATTEMPT_OWNER_PID_FIELD))
    recorded_live = bool(meta.get(ATTEMPT_LIVE_FIELD))
    live = recorded_live and (owner_pid is None or is_process_running(owner_pid))
    return {
        "attempt_id": attempt_id,
        "fingerprint": _str(meta.get(ATTEMPT_FINGERPRINT_FIELD)) or fingerprint or None,
        "stage": _str(meta.get(ATTEMPT_STAGE_FIELD)),
        "live": live,
        "owner_pid": owner_pid,
        "started_at": _str(meta.get(ATTEMPT_STARTED_AT_FIELD)),
        "error_stage": _str(meta.get(ERROR_STAGE_FIELD)),
        "error_type": _str(meta.get(ERROR_TYPE_FIELD)),
        "error_message": _str(meta.get(ERROR_MESSAGE_FIELD)),
    }


def persist_attempt(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    stage: str,
    live: bool,
    fingerprint: str,
    error: BaseException | None = None,
    error_stage: str | None = None,
) -> None:
    """Write attempt identity and liveness onto gate metadata before/after work."""
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    gate_id = _str(meta.get("gate_id")) or ""
    attempt_id = gate_followup_attempt_id(gate_id, fingerprint)
    values: dict[str, Any] = {
        ATTEMPT_ID_FIELD: attempt_id,
        ATTEMPT_FINGERPRINT_FIELD: fingerprint or None,
        ATTEMPT_STAGE_FIELD: stage,
        ATTEMPT_LIVE_FIELD: live,
        ATTEMPT_OWNER_PID_FIELD: (
            os.getpid() if live else meta.get(ATTEMPT_OWNER_PID_FIELD)
        ),
        ATTEMPT_STARTED_AT_FIELD: (
            _str(meta.get(ATTEMPT_STARTED_AT_FIELD))
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ),
    }
    if error is not None:
        values[ERROR_STAGE_FIELD] = error_stage or stage
        values[ERROR_TYPE_FIELD] = type(error).__name__
        values[ERROR_MESSAGE_FIELD] = str(error)
        values[ATTEMPT_LIVE_FIELD] = False
        values["gate_followup_error"] = (
            f"{error_stage or stage}: {type(error).__name__}: {error}"
        )
        values["gate_followup_outcome"] = "failed"
    for key, value in values.items():
        if value is None:
            continue
        meta[key] = value
        update_meta_field(artifacts_dir, key, value)


def collect_successor_evidence(
    *,
    project_name: str | None,
    family: str,
    expected_suffix: str | None,
    recorded_agent: str | None,
) -> dict[str, Any]:
    """Inspect family attachment/launch evidence without starting a provider."""
    suffix = expected_suffix or PLAN_CHAIN_CODER_SUFFIX
    matches: list[tuple[str, bool, bool]] = []
    for record in _family_records(project_name, family):
        name = _record_name(record)
        if not name or not name.endswith(suffix):
            continue
        running = record.running is not None
        completed = record.done is not None
        matches.append((name, running, completed))
    if recorded_agent:
        named = [item for item in matches if item[0] == recorded_agent]
        if named:
            matches = named
    if len(matches) > 1:
        running_or_done = [item for item in matches if item[1] or item[2]]
        if len(running_or_done) != 1:
            return {
                "family_name": family,
                "expected_suffix": suffix,
                "ambiguous": True,
                "running": any(item[1] for item in matches),
                "completed": any(item[2] for item in matches),
            }
        matches = running_or_done
    if not matches:
        return {
            "family_name": family,
            "expected_suffix": suffix,
            "attached_agent": recorded_agent,
            "running": False,
            "completed": False,
            "ambiguous": False,
        }
    name, running, completed = matches[0]
    return {
        "family_name": family,
        "expected_suffix": suffix,
        "attached_agent": name,
        "launch_receipt": recorded_agent,
        "running": running,
        "completed": completed,
        "ambiguous": False,
    }


def apply_decision(
    artifacts_dir: str,
    meta: dict[str, Any],
    decision: Mapping[str, Any],
) -> None:
    """Persist classifier-selected outcome, agent, and attention fields."""
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    persist_outcome = decision.get("persist_outcome")
    if isinstance(persist_outcome, str) and persist_outcome:
        meta["gate_followup_outcome"] = persist_outcome
        update_meta_field(artifacts_dir, "gate_followup_outcome", persist_outcome)
    adopt_agent = decision.get("adopt_agent")
    if (
        isinstance(adopt_agent, str)
        and adopt_agent
        and not meta.get("gate_followup_agent")
    ):
        meta["gate_followup_agent"] = adopt_agent
        update_meta_field(artifacts_dir, "gate_followup_agent", adopt_agent)
    if decision.get("needs_attention") and not meta.get("gate_followup_error"):
        reason = str(decision.get("reason") or "follow-up needs attention")
        meta["gate_followup_error"] = reason
        update_meta_field(artifacts_dir, "gate_followup_error", reason)


def notify_handoff_failure(
    meta: Mapping[str, Any],
    *,
    error: BaseException | str,
    stage: str,
) -> None:
    """Publish one durable failure notification keyed to the attempt."""
    gate_id = _str(meta.get("gate_id")) or ""
    kind = _str(meta.get("gate_kind")) or "plan"
    member = _str(meta.get("name")) or ""
    selected = _selected_option_flags(meta)
    resume = f"sase gate answer --kind {kind} --id {gate_id}{selected} --resume"
    notes = [
        f"Gate follow-up failed for {member or gate_id}",
        f"Stage: {stage}",
        f"{type(error).__name__ if isinstance(error, BaseException) else 'Error'}: "
        f"{error}",
        f"Resume with: {resume}",
    ]
    try:
        from sase.notifications.senders import notify_workflow_complete

        notify_workflow_complete(
            sender="gate",
            cl_name=_str(meta.get("cl_name")),
            success=False,
            notes=notes,
            action="ViewErrorReport",
            action_data={
                "gate_id": gate_id,
                "gate_kind": kind,
                "attempt_id": _str(meta.get(ATTEMPT_ID_FIELD)) or "",
                "resume_command": resume,
                **({"agent_name": member} if member else {}),
            },
            tags=["gate", "followup", "error"],
        )
    except Exception:
        logger.warning(
            "Failed to send gate follow-up error notification", exc_info=True
        )


def resume_command_for(meta: Mapping[str, Any]) -> str:
    """Return the supported CLI resume command for this gate."""
    gate_id = _str(meta.get("gate_id")) or ""
    kind = _str(meta.get("gate_kind")) or "plan"
    return f"sase gate answer --kind {kind} --id {gate_id}{_selected_option_flags(meta)} --resume"


def merge_followup_fields(memory: dict[str, Any], disk: Mapping[str, Any]) -> None:
    """Copy follow-up fields written during launch back onto the settlement dict."""
    for key, value in disk.items():
        if key.startswith("gate_followup_") or key.startswith("gate_next_"):
            memory[key] = value


def _family_records(
    project_name: str | None, family: str
) -> list[AgentArtifactRecordWire]:
    if not family:
        return []
    options = AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        only_projects=(project_name,) if project_name else (),
        max_records=None,
        newest_first=False,
    )
    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=True,
        active_limit=None,
        recent_completed_limit=None,
        include_hidden=True,
        only_monitors=False,
    )
    index_path = default_agent_artifact_index_path()
    try:
        scan = query_agent_artifact_index(
            index_path, sase_projects_dir(), query, options
        )
        records = list(scan.records)
    except (OSError, RuntimeError, ValueError, ImportError, AttributeError):
        return []
    matches: list[AgentArtifactRecordWire] = []
    for record in records:
        meta = record.agent_meta
        if meta is None or meta.agent_family != family:
            continue
        matches.append(record)
    return matches


def _record_name(record: AgentArtifactRecordWire) -> str | None:
    meta = record.agent_meta
    if meta is None:
        return None
    return meta.name or None


def _selected_option_flags(meta: Mapping[str, Any]) -> str:
    selected = meta.get("gate_selected_option_ids")
    if not isinstance(selected, list) or not selected:
        return ""
    return "".join(f" --option {option_id}" for option_id in selected if option_id)


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_reconcile_cursor(project_name: str) -> dict[str, Any]:
    """Return persisted bounded-reconciliation progress for one project."""
    path = _cursor_path(project_name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def store_reconcile_cursor(project_name: str, cursor: Mapping[str, Any]) -> None:
    """Persist bounded-reconciliation progress for one project."""
    path = _cursor_path(project_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(cursor), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _cursor_path(project_name: str) -> Path:
    return sase_projects_dir() / project_name / "artifacts" / RECONCILE_CURSOR_NAME


__all__ = [
    "ATTEMPT_ID_FIELD",
    "ERROR_MESSAGE_FIELD",
    "ERROR_STAGE_FIELD",
    "ERROR_TYPE_FIELD",
    "FOLLOWUP_LOCK_NAME",
    "RECONCILE_BATCH_SIZE",
    "apply_decision",
    "classify_gate_handoff",
    "collect_successor_evidence",
    "load_reconcile_cursor",
    "merge_followup_fields",
    "notify_handoff_failure",
    "persist_attempt",
    "resume_command_for",
    "store_reconcile_cursor",
    "with_gate_followup_lock",
]
