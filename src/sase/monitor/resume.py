"""Manual monitor continuation resume and terminal-delivery recovery."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from typing import Any

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.continuation_capture import (
    AuthoredCheckpoint,
    AuthoredCheckpointError,
    load_authored_checkpoint,
    persist_monitor_start_intent,
)
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.finalizers.declaration_store import write_json_atomic
from sase.shells.settlement import stamp_shell_finished_at
from sase.workflows.utils import get_project_file_path

from .delivery import (
    delivery_store_lock,
    load_delivery_record,
    load_delivery_records,
    persist_delivery_record,
    transition_delivery,
)
from .diagnostics import diagnostic_manifest, retained_log_metadata
from .followup import (
    FollowupLaunchResult,
    launch_followup_agent,
    load_frozen_monitor_result,
)
from .logs import monitor_log_path
from .models import MonitorError, MonitorRecord
from .naming import short_monitor_id
from .output import OutputCapture
from .result_projection import build_monitor_result_wire

_ACTIVE_DELIVERY_STATES = frozenset({"pending", "reserved", "dispatching"})
_DELIVERED_STATES = frozenset({"acknowledged", "settled"})
_MANUAL_BRANCH_RE = re.compile(r"^manual-recovery-(\d+)$")


class MonitorResumeError(MonitorError):
    """A monitor cannot be resumed safely."""

    def __init__(
        self,
        message: str,
        *,
        suggested_command: str | None = None,
        code: str = "not_resumable",
    ) -> None:
        super().__init__(message)
        self.suggested_command = suggested_command
        self.code = code


@dataclass(frozen=True, slots=True)
class MonitorResumeResult:
    """Result of a monitor resume or terminal delivery reconciliation."""

    monitor_id: str
    branch: str
    agent_name: str | None
    delivery_disposition: str | None
    launched: bool
    spawned: bool
    manual_revision: bool = False
    reused_revision: bool = False
    ownership_outcome: str = "unknown"
    message: str = ""


def resume_monitor(
    record: MonitorRecord,
    *,
    checkpoint_path: str | None = None,
    model: str | None = None,
) -> MonitorResumeResult:
    """Resume one terminal monitor's requested ordinary continuation."""

    meta = _read_meta(record.artifacts_dir)
    checkpoint = _load_checkpoint(checkpoint_path)
    selected_model = _selected_model(meta, model)
    result = _monitor_result(record, meta)
    monitor_id = str(result.get("monitor_id") or record.monitor_id or "monitor")
    result_id = str(result.get("result_id") or record.monitor_result_id or "result")
    _validate_resume_request(
        record,
        meta,
        checkpoint=checkpoint,
        model=model,
        suggested_command=_suggested_command(record),
    )

    base_branch = _base_branch(result, record)
    existing = _delivery_records(
        record,
        monitor_id=monitor_id,
        result_id=result_id,
    )
    delivered = _first_record(existing, _DELIVERED_STATES)
    if delivered is not None:
        if checkpoint is not None or model is not None:
            raise MonitorResumeError(
                "monitor continuation has already been acknowledged; checkpoint "
                "or model changes cannot be applied after handoff",
                suggested_command=None,
                code="already_delivered",
            )
        return _existing_delivery_result(record, delivered, outcome="already_delivered")

    manual_revision = checkpoint is not None or model is not None
    if manual_revision:
        branch, reused = _allocate_manual_branch(
            record.artifacts_dir,
            monitor_id=monitor_id,
            result_id=result_id,
            checkpoint=checkpoint,
            selected_model=selected_model,
            next_action=str(meta.get("monitor_next_action") or ""),
        )
        _supersede_active_records(
            record.artifacts_dir,
            existing,
            branch=branch,
        )
        checkpoint_ref = _persist_manual_intent_revision(
            record,
            meta,
            branch=branch,
            checkpoint=checkpoint,
            selected_model=selected_model,
        )
    else:
        active = _first_record(existing, _ACTIVE_DELIVERY_STATES)
        branch = (
            str((active or {}).get("key", {}).get("branch") or "")
            if active is not None
            else base_branch
        )
        reused = False
        checkpoint_ref = None

    active_record = load_delivery_record(
        record.artifacts_dir,
        {"monitor_id": monitor_id, "result_id": result_id, "branch": branch},
    )
    if active_record is not None:
        disposition = str(active_record.get("disposition") or "")
        if disposition in _DELIVERED_STATES:
            return _existing_delivery_result(
                record,
                active_record,
                outcome="already_delivered",
                manual_revision=manual_revision,
                reused_revision=reused,
            )
        if disposition == "dispatching":
            receiver = _confirmed_receiver(record.project_name, active_record)
            if receiver is not None:
                _record_successful_resume(record, meta, receiver)
                return MonitorResumeResult(
                    monitor_id=monitor_id,
                    branch=branch,
                    agent_name=receiver,
                    delivery_disposition=disposition,
                    launched=True,
                    spawned=False,
                    manual_revision=manual_revision,
                    reused_revision=reused,
                    ownership_outcome="existing_receiver",
                    message=f"Monitor {short_monitor_id(monitor_id)} already handed off to {receiver}.",
                )

    launch = _launch_resume(
        record,
        meta,
        branch=branch,
        selected_model=selected_model if model is not None else None,
        checkpoint_ref=checkpoint_ref,
        retryable_pre_dispatch_failure=(
            active_record is not None
            and str(active_record.get("disposition") or "") == "dispatching"
        ),
    )
    if not launch.launched:
        reason = launch.error or "follow-up launch failed"
        _mark_delivery_needs_attention(
            record.artifacts_dir,
            monitor_id=monitor_id,
            result_id=result_id,
            branch=branch,
            reason=reason,
        )
        raise MonitorResumeError(
            f"{reason}; retry with `{_suggested_command(record)}`",
            suggested_command=_suggested_command(record),
            code="launch_failed",
        )

    agent_name = launch.agent_name or _delivery_identity(
        load_delivery_record(
            record.artifacts_dir,
            {"monitor_id": monitor_id, "result_id": result_id, "branch": branch},
        )
    )
    _record_successful_resume(record, meta, agent_name)
    current = load_delivery_record(
        record.artifacts_dir,
        {"monitor_id": monitor_id, "result_id": result_id, "branch": branch},
    )
    delivery_disposition = str((current or {}).get("disposition") or "") or None
    return MonitorResumeResult(
        monitor_id=monitor_id,
        branch=branch,
        agent_name=agent_name,
        delivery_disposition=delivery_disposition,
        launched=True,
        spawned=True,
        manual_revision=manual_revision,
        reused_revision=reused,
        ownership_outcome="spawned_receiver",
        message=f"Resumed monitor {short_monitor_id(monitor_id)} with {agent_name}.",
    )


def reconcile_terminal_delivery(record: MonitorRecord) -> MonitorResumeResult | None:
    """Recover an already-created terminal delivery without creating a new one."""

    if record.monitor_state in {"running", "stopped", "lost"}:
        return None
    if not record.next_action:
        return None
    meta = _read_meta(record.artifacts_dir)
    result = _monitor_result(record, meta)
    monitor_id = str(result.get("monitor_id") or record.monitor_id or "monitor")
    result_id = str(result.get("result_id") or record.monitor_result_id or "result")
    existing = _delivery_records(record, monitor_id=monitor_id, result_id=result_id)
    if _first_record(existing, _ACTIVE_DELIVERY_STATES) is None:
        return None
    try:
        return resume_monitor(record)
    except MonitorResumeError as exc:
        _record_resume_error(record, meta, str(exc))
        return None


def _validate_resume_request(
    record: MonitorRecord,
    meta: Mapping[str, Any],
    *,
    checkpoint: AuthoredCheckpoint | None,
    model: str | None,
    suggested_command: str,
) -> None:
    if record.monitor_state == "running":
        raise MonitorResumeError(
            "monitor is still running; wait for it to finish before resuming",
            suggested_command=None,
            code="still_running",
        )
    if record.monitor_state in {"stopped", "lost"}:
        raise MonitorResumeError(
            f"monitor is {record.monitor_state}; that state is inspection-only",
            suggested_command=None,
            code=record.monitor_state,
        )
    if not str(meta.get("monitor_next_action") or "").strip():
        raise MonitorResumeError(
            "monitor was fire-and-forget and has no requested next action",
            suggested_command=None,
            code="fire_and_forget",
        )
    if _conditional_completion_state(meta, record):
        raise MonitorResumeError(
            "monitor resume cannot retry conditional host finalization",
            suggested_command=None,
            code="conditional_completion",
        )
    if _capture_needs_recovery(meta) and checkpoint is None and model is None:
        raise MonitorResumeError(
            f"monitor context capture needs manual recovery; retry with `{suggested_command} -k FILE`",
            suggested_command=f"{suggested_command} -k FILE",
            code="capture_recovery",
        )


def _launch_resume(
    record: MonitorRecord,
    meta: dict[str, Any],
    *,
    branch: str,
    selected_model: str | None,
    checkpoint_ref: str | None,
    retryable_pre_dispatch_failure: bool,
) -> FollowupLaunchResult:
    capture = _capture_from_log(record)
    return launch_followup_agent(
        record.artifacts_dir,
        meta,
        monitor_state=record.monitor_state,
        exit_code=record.exit_code,
        elapsed_seconds=record.elapsed_seconds or _elapsed_seconds(meta),
        capture=capture,
        timeout_kind=meta.get("monitor_timeout_kind")
        if isinstance(meta.get("monitor_timeout_kind"), str)
        else None,
        project_name=record.project_name,
        transfer_from_pid=record.pid,
        branch_override=branch,
        next_model_override=selected_model,
        checkpoint_ref_override=checkpoint_ref,
        retryable_pre_dispatch_failure=retryable_pre_dispatch_failure,
    )


def _monitor_result(record: MonitorRecord, meta: dict[str, Any]) -> Mapping[str, Any]:
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
        elapsed_seconds=record.elapsed_seconds or _elapsed_seconds(meta),
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


def _delivery_records(
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


def _first_record(
    records: list[dict[str, Any]],
    dispositions: frozenset[str],
) -> dict[str, Any] | None:
    for record in records:
        if str(record.get("disposition") or "") in dispositions:
            return record
    return None


def _existing_delivery_result(
    record: MonitorRecord,
    delivery: Mapping[str, Any],
    *,
    outcome: str,
    manual_revision: bool = False,
    reused_revision: bool = False,
) -> MonitorResumeResult:
    identity = _delivery_identity(delivery)
    if identity:
        meta = _read_meta(record.artifacts_dir)
        _record_successful_resume(record, meta, identity)
    raw_key = delivery.get("key")
    key = raw_key if isinstance(raw_key, Mapping) else {}
    branch = str(key.get("branch") or _base_branch({}, record))
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


def _record_successful_resume(
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


def _record_resume_error(
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


def _mark_delivery_needs_attention(
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
    if str(record.get("disposition") or "") in _DELIVERED_STATES:
        return
    try:
        persist_delivery_record(
            artifacts_dir,
            transition_delivery(record, "needs_attention", reason=reason),
        )
    except Exception:
        return


def _supersede_active_records(
    artifacts_dir: str,
    records: list[dict[str, Any]],
    *,
    branch: str,
) -> None:
    for record in records:
        disposition = str(record.get("disposition") or "")
        if disposition not in _ACTIVE_DELIVERY_STATES:
            continue
        raw_key = record.get("key")
        key = raw_key if isinstance(raw_key, Mapping) else {}
        if key.get("branch") == branch:
            continue
        persist_delivery_record(
            artifacts_dir,
            transition_delivery(
                record,
                "needs_attention",
                reason=f"superseded by manual resume branch {branch}",
            ),
        )


def _persist_manual_intent_revision(
    record: MonitorRecord,
    meta: dict[str, Any],
    *,
    branch: str,
    checkpoint: AuthoredCheckpoint | None,
    selected_model: str | None,
) -> str | None:
    checkpoint_ref = checkpoint.content_ref if checkpoint is not None else None
    checkpoint_document = checkpoint.payload if checkpoint is not None else None
    persist_monitor_start_intent(
        artifacts_dir=record.artifacts_dir,
        monitor_id=record.monitor_id,
        member_agent_name=record.member_agent_name,
        project_name=record.project_name,
        command=record.command,
        cwd=record.cwd,
        next_action=str(meta.get("monitor_next_action") or ""),
        next_model=selected_model,
        next_output=str(meta.get("monitor_next_output") or record.next_output),
        request_fingerprint=str(meta.get("monitor_request_fingerprint") or ""),
        parent_node_ids=tuple(
            item
            for item in meta.get("continuation_parent_node_ids", [])
            if isinstance(item, str)
        ),
        starter_agent=(
            str(meta.get("monitor_starter_agent"))
            if meta.get("monitor_starter_agent")
            else None
        ),
        checkpoint_ref=checkpoint_ref,
        checkpoint_document=checkpoint_document,
        starter_artifacts_dir=(
            str(meta.get("monitor_starter_artifacts_dir"))
            if meta.get("monitor_starter_artifacts_dir")
            else None
        ),
        intent_revision=branch,
        allow_missing_validation=True,
    )
    refreshed = _read_meta(record.artifacts_dir)
    meta.clear()
    meta.update(refreshed)
    return str(meta.get("continuation_checkpoint_ref") or checkpoint_ref or "")


def _allocate_manual_branch(
    artifacts_dir: str,
    *,
    monitor_id: str,
    result_id: str,
    checkpoint: AuthoredCheckpoint | None,
    selected_model: str | None,
    next_action: str,
) -> tuple[str, bool]:
    fingerprint = _manual_revision_fingerprint(
        monitor_id=monitor_id,
        result_id=result_id,
        checkpoint_ref=checkpoint.content_ref if checkpoint is not None else None,
        selected_model=selected_model,
        next_action=next_action,
    )
    root = Path(artifacts_dir) / "continuation" / "manual_resume"
    with delivery_store_lock(artifacts_dir):
        root.mkdir(parents=True, exist_ok=True)
        for path in sorted(root.glob("manual-recovery-*.json")):
            payload = _read_json_object(path)
            if payload.get("fingerprint") == fingerprint:
                branch = str(payload.get("branch") or "")
                if branch:
                    return branch, True
        used = _used_manual_branch_numbers(root, artifacts_dir)
        number = 1
        while number in used:
            number += 1
        branch = f"manual-recovery-{number}"
        payload = {
            "schema_version": 1,
            "kind": "manual_monitor_resume",
            "branch": branch,
            "fingerprint": fingerprint,
            "monitor_id": monitor_id,
            "result_id": result_id,
            "checkpoint_ref": checkpoint.content_ref
            if checkpoint is not None
            else None,
            "next_model": selected_model,
            "recorded_at": _utc_now_iso(),
        }
        write_json_atomic(root / f"{branch}.json", payload)
        return branch, False


def _used_manual_branch_numbers(root: Path, artifacts_dir: str) -> set[int]:
    used: set[int] = set()
    for path in root.glob("manual-recovery-*.json"):
        payload = _read_json_object(path)
        number = _manual_branch_number(str(payload.get("branch") or path.stem))
        if number is not None:
            used.add(number)
    for record in load_delivery_records(artifacts_dir):
        raw_key = record.get("key")
        key = raw_key if isinstance(raw_key, Mapping) else {}
        number = _manual_branch_number(str(key.get("branch") or ""))
        if number is not None:
            used.add(number)
    return used


def _manual_branch_number(branch: str) -> int | None:
    match = _MANUAL_BRANCH_RE.match(branch)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _manual_revision_fingerprint(
    *,
    monitor_id: str,
    result_id: str,
    checkpoint_ref: str | None,
    selected_model: str | None,
    next_action: str,
) -> str:
    payload = {
        "monitor_id": monitor_id,
        "result_id": result_id,
        "checkpoint_ref": checkpoint_ref,
        "selected_model": selected_model,
        "next_action": next_action,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _confirmed_receiver(
    project_name: str,
    delivery: Mapping[str, Any],
) -> str | None:
    identity = _delivery_identity(delivery)
    if not identity:
        return None
    try:
        from .store import resolve_exact_agent

        resolve_exact_agent(project_name, identity)
    except Exception:
        return None
    return identity


def _delivery_identity(delivery: Mapping[str, Any] | None) -> str | None:
    if not delivery:
        return None
    for key in ("acknowledged_by", "reserved_identity"):
        value = delivery.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _base_branch(result: Mapping[str, Any], record: MonitorRecord) -> str:
    branch = result.get("outcome")
    if isinstance(branch, str) and branch:
        return branch
    return record.monitor_state if record.monitor_state != "running" else "unknown"


def _selected_model(meta: Mapping[str, Any], model: str | None) -> str | None:
    if model is not None:
        stripped = model.strip()
        return stripped or None
    existing = meta.get("monitor_next_model")
    return existing if isinstance(existing, str) and existing.strip() else None


def _load_checkpoint(path: str | None) -> AuthoredCheckpoint | None:
    if not path:
        return None
    try:
        return load_authored_checkpoint(path)
    except AuthoredCheckpointError:
        raise


def _capture_from_log(record: MonitorRecord) -> OutputCapture:
    capture = OutputCapture()
    path = (
        Path(record.output_path)
        if record.output_path
        else monitor_log_path(record.artifacts_dir)
    )
    for candidate in (path.with_name(f"{path.name}.1"), path):
        try:
            data = candidate.read_bytes()
        except OSError:
            continue
        if data:
            capture.append_bytes(data)
    return capture


def _elapsed_seconds(meta: Mapping[str, Any]) -> float:
    started = _parse_time(meta.get("run_started_at"))
    stopped = _parse_time(meta.get("stopped_at"))
    if started is None or stopped is None:
        return 0.0
    return max(0.0, (stopped - started).total_seconds())


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _conditional_completion_state(
    meta: Mapping[str, Any],
    record: MonitorRecord,
) -> bool:
    status = meta.get("monitor_host_completion_status") or record.host_completion_status
    if isinstance(status, str) and status:
        return True
    return False


def _capture_needs_recovery(meta: Mapping[str, Any]) -> bool:
    return str(meta.get("continuation_capture_disposition") or "") == "needs_recovery"


def _suggested_command(record: MonitorRecord) -> str:
    return f"sase monitor resume {short_monitor_id(record.monitor_id)}"


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    return _read_json_object(Path(artifacts_dir) / "agent_meta.json")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "MonitorResumeError",
    "MonitorResumeResult",
    "reconcile_terminal_delivery",
    "resume_monitor",
]
