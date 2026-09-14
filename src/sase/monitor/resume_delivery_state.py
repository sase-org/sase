"""Delivery-record lookups and resume-outcome recording for monitor resume."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.shells.settlement import stamp_shell_finished_at
from sase.workflows.utils import get_project_file_path

from .delivery import (
    load_delivery_record,
    load_delivery_records,
    persist_delivery_record,
    transition_delivery,
)
from .diagnostics import diagnostic_manifest, retained_log_metadata
from .followup import load_frozen_monitor_result
from .models import MonitorRecord
from .naming import short_monitor_id
from .resume_support import MonitorResumeResult, elapsed_seconds, read_meta
from .result_projection import build_monitor_result_wire

DELIVERED_STATES = frozenset({"acknowledged", "settled"})


def monitor_result(record: MonitorRecord, meta: dict[str, Any]) -> Mapping[str, Any]:
    frozen = load_frozen_monitor_result(record.artifacts_dir, meta)
    if frozen is not None:
        return frozen
    manifest = diagnostic_manifest(record.artifacts_dir)
    retained = retained_log_metadata(record.artifacts_dir)
    return build_monitor_result_wire(
        monitor_id=record.monitor_id,
        monitor_state=record.monitor_state,
        exit_code=record.exit_code,
        command=meta.get("monitor_execution_argv") or record.command,
        cwd=record.cwd or str(meta.get("monitor_cwd") or ""),
        started_at=meta.get("run_started_at"),
        stopped_at=meta.get("stopped_at"),
        elapsed_seconds=record.elapsed_seconds or elapsed_seconds(meta),
        timeout_seconds=record.timeout_seconds,
        timeout_kind=meta.get("monitor_timeout_kind"),
        starter_execution_id=meta.get("monitor_starter_agent")
        or meta.get("parent_timestamp"),
        workspace_identity=meta.get("continuation_workspace_ref")
        or meta.get("workspace_dir")
        or meta.get("workspace_num"),
        diagnostic_manifest_ref=manifest.get("manifest_ref"),
        retained_log=retained,
    )


def delivery_records(
    record: MonitorRecord,
    *,
    monitor_id: str,
    result_id: str,
) -> list[dict[str, Any]]:
    records = load_delivery_records(
        record.artifacts_dir,
        monitor_id=monitor_id,
        result_id=result_id,
    )
    return [item for item in records if item.get("selected_action") == "continue"]


def first_record(
    records: list[dict[str, Any]],
    dispositions: frozenset[str],
) -> dict[str, Any] | None:
    for record in records:
        if str(record.get("disposition") or "") in dispositions:
            return record
    return None


def existing_delivery_result(
    record: MonitorRecord,
    delivery: Mapping[str, Any],
    *,
    outcome: str,
    manual_revision: bool = False,
    reused_revision: bool = False,
) -> MonitorResumeResult:
    identity = delivery_identity(delivery)
    if identity:
        meta = read_meta(record.artifacts_dir)
        record_successful_resume(record, meta, identity)
    raw_key = delivery.get("key")
    key = raw_key if isinstance(raw_key, Mapping) else {}
    branch = str(key.get("branch") or base_branch({}, record))
    disposition = str(delivery.get("disposition") or "") or None
    return MonitorResumeResult(
        monitor_id=record.monitor_id,
        branch=branch,
        agent_name=identity,
        delivery_disposition=disposition,
        launched=bool(identity),
        spawned=False,
        manual_revision=manual_revision,
        reused_revision=reused_revision,
        ownership_outcome=outcome,
        message=(
            f"Monitor {short_monitor_id(record.monitor_id)} already handed off to {identity}."
            if identity
            else f"Monitor {short_monitor_id(record.monitor_id)} has existing delivery {disposition}."
        ),
    )


def record_successful_resume(
    record: MonitorRecord,
    meta: dict[str, Any],
    agent_name: str | None,
) -> None:
    if not agent_name:
        return
    meta["monitor_followup_agent"] = agent_name
    meta["monitor_followup_outcome"] = "launched"
    for key in ("monitor_followup_error", "monitor_followup_prompt_path"):
        meta.pop(key, None)
    write_agent_meta_atomic(
        record.artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )
    done_path = Path(record.artifacts_dir) / "done.json"
    try:
        done = json.loads(done_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return
    if not isinstance(done, dict):
        return
    done["monitor_followup_agent"] = agent_name
    done["monitor_followup_outcome"] = "launched"
    for key in ("monitor_followup_error", "monitor_followup_prompt_path"):
        done.pop(key, None)
    done.setdefault("project_file", get_project_file_path(record.project_name))
    done.setdefault("outcome", "monitored")
    done.setdefault("monitor_state", record.monitor_state)
    done.setdefault("monitor_exit_code", record.exit_code)
    done.setdefault("monitor_elapsed_seconds", record.elapsed_seconds)
    stamp_shell_finished_at(done)
    write_done_marker_and_update_index(record.artifacts_dir, done)


def record_resume_error(
    record: MonitorRecord,
    meta: dict[str, Any],
    message: str,
) -> None:
    meta["monitor_followup_outcome"] = "not-launchable"
    meta["monitor_followup_error"] = message
    write_agent_meta_atomic(
        record.artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )


def mark_delivery_needs_attention(
    artifacts_dir: str,
    *,
    monitor_id: str,
    result_id: str,
    branch: str,
    reason: str,
) -> None:
    record = load_delivery_record(
        artifacts_dir,
        {"monitor_id": monitor_id, "result_id": result_id, "branch": branch},
    )
    if record is None:
        return
    if str(record.get("disposition") or "") in DELIVERED_STATES:
        return
    try:
        persist_delivery_record(
            artifacts_dir,
            transition_delivery(record, "needs_attention", reason=reason),
        )
    except Exception:
        return


def delivery_identity(delivery: Mapping[str, Any] | None) -> str | None:
    if not delivery:
        return None
    for key in ("acknowledged_by", "reserved_identity"):
        value = delivery.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def base_branch(result: Mapping[str, Any], record: MonitorRecord) -> str:
    branch = result.get("outcome")
    if isinstance(branch, str) and branch:
        return branch
    return record.monitor_state if record.monitor_state != "running" else "unknown"


__all__ = [
    "DELIVERED_STATES",
    "base_branch",
    "delivery_identity",
    "delivery_records",
    "existing_delivery_result",
    "first_record",
    "mark_delivery_needs_attention",
    "monitor_result",
    "record_resume_error",
    "record_successful_resume",
]
