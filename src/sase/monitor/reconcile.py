"""Dead-supervisor reconciliation for monitor family members."""

from __future__ import annotations

import json
import os
import signal
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.history.chat import save_chat_history
from sase.logs._bounded import log_file_lock
from sase.workflows.utils import get_project_file_path

from .identity import supervisor_is_alive
from .logs import append_monitor_log_bytes, monitor_log_path
from .models import MonitorRecord, MonitorState
from .output import OutputCapture
from .settlement import (
    finalize_monitor_workflow_state,
    settle_claim_and_followup,
    touch_monitor_refresh_pulse,
)
from .transaction import monitor_lane_lock_path

_DEAD_SUPERVISOR_ERROR = "monitor supervisor died without reporting"
_LOST_SUPERVISOR_ERROR = (
    "monitor supervisor belongs to a previous boot; command outcome is unknown"
)

_RECONCILE_KILL_GRACE_SECONDS = 5.0
_RECONCILE_KILL_POLL_SECONDS = 0.05
_PROC_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")

GetMonitor = Callable[[str, str], MonitorRecord | None]


def should_reconcile_dead_supervisor(record: MonitorRecord) -> bool:
    """Return whether a running monitor's supervisor needs reconciliation."""
    from .proc_adapter import proc_shell_owns

    if proc_shell_owns(record.monitor_id):
        return False
    if record.monitor_state != "running":
        return False
    if record.pid is None:
        return False
    if _is_pre_reboot_monitor(record):
        return True
    return not supervisor_is_alive(record.pid, record.supervisor_identity)


def reconcile_dead_supervisor(
    record: MonitorRecord,
    *,
    get_monitor: GetMonitor,
) -> MonitorRecord:
    """Settle a running monitor after its supervisor died without reporting."""
    if not record.lane:
        return record
    with log_file_lock(monitor_lane_lock_path(record.project_name, record.lane)):
        current = get_monitor(record.project_name, record.artifacts_dir)
        if current is None or current.monitor_state != "running":
            return current if current is not None else record
        candidate = _with_liveness_fallback(current, record)
        if not should_reconcile_dead_supervisor(candidate):
            return current
        return _reconcile_dead_supervisor_locked(candidate, get_monitor=get_monitor)


def reconcile_dead_supervisors_for_records(
    records: Iterable[AgentArtifactRecordWire],
    *,
    get_monitor: GetMonitor,
) -> list[MonitorRecord]:
    """Reconcile every running monitor whose supervisor is no longer alive."""
    reconciled: list[MonitorRecord] = []
    for wire_record in records:
        try:
            record = MonitorRecord.from_record(wire_record)
        except ValueError:
            continue
        if not should_reconcile_dead_supervisor(record):
            continue
        updated = reconcile_dead_supervisor(record, get_monitor=get_monitor)
        if updated.monitor_state != "running":
            reconciled.append(updated)
    return reconciled


def _reconcile_dead_supervisor_locked(
    record: MonitorRecord,
    *,
    get_monitor: GetMonitor,
) -> MonitorRecord:
    meta_path = os.path.join(record.artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return record
    if meta.get("monitor_state") != "running":
        current = get_monitor(record.project_name, record.artifacts_dir)
        return current if current is not None else record

    monitor_state: MonitorState = "lost" if _is_pre_reboot_monitor(record) else "failed"
    error = (
        _LOST_SUPERVISOR_ERROR if monitor_state == "lost" else _DEAD_SUPERVISOR_ERROR
    )
    if monitor_state != "lost":
        kill_error = _kill_monitor_process_group(record.pgid)
        if kill_error:
            error = f"{error}; {kill_error}"

    capture = _capture_existing_output(record.artifacts_dir)
    _append_reconcile_log_line(record.artifacts_dir, capture, error)

    stopped_at = _utc_now_iso()
    elapsed_seconds = _elapsed_seconds(meta, stopped_at)
    stop_status = str(meta.get("monitor_stop_status") or "MONITORED")

    meta["monitor_state"] = monitor_state
    meta["monitor_output_truncated"] = capture.truncated
    meta["stopped_at"] = stopped_at
    write_agent_meta_atomic(
        record.artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )

    response_path = save_chat_history(
        f"sase monitor start --command {meta.get('monitor_command')!r} "
        f"--reason {meta.get('monitor_reason')!r}",
        capture.retained_text(),
        "ace-run",
        agent=str(meta.get("name") or ""),
        timestamp=os.path.basename(record.artifacts_dir.rstrip("/")),
        branch_or_workspace=_optional_str(meta.get("cl_name")) or record.lane,
        metadata_agent=str(meta.get("name") or ""),
        metadata_model=_optional_str(meta.get("model")),
        metadata_llm_provider=_optional_str(meta.get("llm_provider")),
    )

    followup_error = settle_claim_and_followup(
        record.artifacts_dir,
        meta,
        monitor_state=monitor_state,
        exit_code=None,
        elapsed_seconds=elapsed_seconds,
        capture=capture,
        timeout_kind=None,
        project_name=record.project_name,
        transfer_from_pid=record.pid,
    )

    meta["monitor_settled"] = True
    write_agent_meta_atomic(
        record.artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )

    done_marker: dict[str, object] = {
        "outcome": "monitored",
        "name": meta.get("name"),
        "cl_name": meta.get("cl_name"),
        "workspace_dir": meta.get("workspace_dir"),
        "workspace_num": meta.get("workspace_num"),
        "monitor_state": monitor_state,
        "monitor_exit_code": None,
        "monitor_elapsed_seconds": elapsed_seconds,
        "status_label": stop_status,
        "response_path": response_path,
        "error": error,
    }
    if record.project_name:
        done_marker["project_file"] = get_project_file_path(record.project_name)
    if followup_error:
        done_marker["monitor_followup_error"] = followup_error
    for key in (
        "monitor_followup_outcome",
        "monitor_followup_degraded_reason",
        "monitor_followup_prompt_path",
    ):
        if meta.get(key):
            done_marker[key] = meta[key]
    write_done_marker_and_update_index(record.artifacts_dir, done_marker)
    finalize_monitor_workflow_state(record.artifacts_dir)
    touch_monitor_refresh_pulse(record.project_name)
    current = get_monitor(record.project_name, record.artifacts_dir)
    return current if current is not None else record


def _is_pre_reboot_monitor(record: MonitorRecord) -> bool:
    recorded = _recorded_boot_id(record.supervisor_identity)
    current = _current_boot_id()
    return bool(recorded and current and recorded != current)


def _with_liveness_fallback(
    current: MonitorRecord,
    original: MonitorRecord,
) -> MonitorRecord:
    if current.pid is not None:
        return current
    return replace(
        current,
        pid=original.pid,
        pgid=current.pgid if current.pgid is not None else original.pgid,
        supervisor_identity=current.supervisor_identity or original.supervisor_identity,
    )


def _current_boot_id() -> str | None:
    """Return the current Linux boot id, or ``None`` when unavailable."""
    try:
        boot_id = _PROC_BOOT_ID_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return boot_id or None


def _recorded_boot_id(recorded_identity: str | None) -> str | None:
    """Return the boot-id component of a recorded process identity."""
    if not recorded_identity:
        return None
    boot_id, separator, _start_ticks = recorded_identity.partition(":")
    if not separator:
        return None
    return boot_id or None


def _kill_monitor_process_group(pgid: int | None) -> str | None:
    if pgid is None:
        return "no process group was recorded"
    if pgid <= 0:
        return f"refusing to signal invalid process group {pgid}"
    if pgid == os.getpgrp():
        return f"refusing to signal current process group {pgid}"

    _signal_process_group(pgid, signal.SIGTERM)
    deadline = time.monotonic() + _RECONCILE_KILL_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not _process_group_exists(pgid):
            return None
        time.sleep(_RECONCILE_KILL_POLL_SECONDS)
    _signal_process_group(pgid, signal.SIGKILL)
    return None


def _signal_process_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _capture_existing_output(artifacts_dir: str) -> OutputCapture:
    capture = OutputCapture()
    path = monitor_log_path(artifacts_dir)
    for candidate in (path.with_name(f"{path.name}.1"), path):
        try:
            data = candidate.read_bytes()
        except OSError:
            continue
        capture.append_bytes(data)
    return capture


def _append_reconcile_log_line(
    artifacts_dir: str,
    capture: OutputCapture,
    message: str,
) -> None:
    encoded = f"{message.rstrip()}\n".encode("utf-8", errors="replace")
    capture.append_bytes(encoded)
    try:
        append_monitor_log_bytes(monitor_log_path(artifacts_dir), encoded)
    except OSError:
        pass


def _elapsed_seconds(meta: Mapping[str, object], stopped_at: str) -> float:
    started_at = meta.get("run_started_at")
    if isinstance(started_at, str) and started_at:
        try:
            start = datetime.fromisoformat(started_at)
            stop = datetime.fromisoformat(stopped_at)
        except ValueError:
            return 0.0
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if stop.tzinfo is None:
            stop = stop.replace(tzinfo=UTC)
        return max(0.0, (stop - start).total_seconds())
    return 0.0


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "reconcile_dead_supervisor",
    "reconcile_dead_supervisors_for_records",
    "should_reconcile_dead_supervisor",
]
