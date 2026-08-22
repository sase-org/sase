"""Project monitors onto the shared proc service and settle family artifacts."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.history.chat import save_chat_history
from sase.monitor_state import MONITOR_PROC_ORIGIN
from sase.monitor_status import clamp_monitor_status_or_default
from sase.procs.models import (
    ACTIVE_PROC_STATUSES,
    PROC_LIFECYCLE_PROC_SHELL,
    TERMINAL_PROC_STATUSES,
    Proc,
    ProcStoreSnapshot,
)
from sase.procs.store import get_proc
from sase.workflows.utils import get_project_file_path

from .followup import launch_followup_agent
from .logs import monitor_log_path
from .models import MonitorRecord, MonitorState
from .output import OutputCapture
from .request import DEFAULT_STOP_STATUS
from .settlement import (
    finalize_monitor_workflow_state,
    project_name_from_artifacts_dir,
    settle_claim_and_followup,
    touch_monitor_refresh_pulse,
)

MONITOR_ARGV_PREFIX: tuple[str, ...] = ("/bin/sh", "-c")
MONITOR_FOLLOWUP_KIND = "monitor"


def compile_monitor_argv(command: str) -> list[str]:
    """Compile a monitor command string to explicit argv."""
    return [*MONITOR_ARGV_PREFIX, command]


def monitor_proc_argv(
    command: str,
    *,
    execution_argv: Sequence[str] | None = None,
) -> list[str]:
    """Return the argv the proc supervisor should exec for a monitor.

    Host-owned epic launches pass an explicit execution argv (the
    code-swap bootstrap). Other monitors keep the historical ``/bin/sh -c``
    form of *command*.
    """
    if execution_argv:
        return [str(part) for part in execution_argv]
    return compile_monitor_argv(command)


def proc_shell_owns(
    monitor_id: str, *, snapshot: ProcStoreSnapshot | None = None
) -> bool:
    """Return whether *monitor_id* is a proc-shell row the facade must not adopt.

    Pass *snapshot* to answer many ownership checks from one store read.
    """
    proc = get_proc(monitor_id, snapshot=snapshot)
    return proc is not None and proc.lifecycle == PROC_LIFECYCLE_PROC_SHELL


def _monitor_state_from_proc(
    proc: Proc, *, termination_reason: str | None = None
) -> MonitorState:
    """Project a proc row onto the monitor family-member state labels."""
    reason = termination_reason or _termination_reason(proc)
    if proc.status in ACTIVE_PROC_STATUSES:
        return "running"
    if reason == "stop" or proc.status == "killed":
        return "stopped"
    if reason in {"total-timeout", "idle-timeout"}:
        return "timeout"
    if reason in {"reboot", "supervisor-loss"}:
        return "lost"
    if proc.status == "success" or reason == "success":
        return "completed"
    return "failed"


def overlay_proc_on_monitor(record: MonitorRecord, proc: Proc) -> MonitorRecord:
    """Overlay live proc execution state onto an artifacts projection."""
    pid = proc.pid if proc.pid is not None else record.pid
    pgid = proc.pgid if proc.pgid is not None else record.pgid
    identity = proc.supervisor_id or record.supervisor_identity
    output_path = proc.log_path or record.output_path
    fingerprint = proc.request_fingerprint or record.request_fingerprint
    if record.settled:
        return replace(
            record,
            pid=pid,
            pgid=pgid,
            supervisor_identity=identity,
            output_path=output_path,
            request_fingerprint=fingerprint,
        )
    reason = _termination_reason(proc)
    monitor_state = _monitor_state_from_proc(proc, termination_reason=reason)
    settled = proc.status in TERMINAL_PROC_STATUSES
    elapsed = _elapsed_seconds(proc)
    return replace(
        record,
        pid=pid,
        pgid=pgid,
        supervisor_identity=identity,
        output_path=output_path,
        exit_code=proc.exit_code if proc.exit_code is not None else record.exit_code,
        monitor_state=monitor_state,
        settled=settled,
        elapsed_seconds=elapsed if elapsed is not None else record.elapsed_seconds,
        request_fingerprint=fingerprint,
    )


def settle_monitor_artifacts(state: dict[str, Any]) -> None:
    """Write family presentation for a monitor whose command is gone."""
    artifacts_dir = state.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return
    meta = _read_meta(artifacts_dir)
    if not meta.get("monitor_id"):
        return
    proc = get_proc(str(state.get("proc_id") or meta.get("monitor_id") or ""))
    termination_reason = str(state.get("termination_reason") or "")
    monitor_state = _monitor_state_from_reason(
        termination_reason, status=str(state.get("status") or "")
    )
    exit_code = state.get("exit_code")
    if not isinstance(exit_code, int):
        exit_code = proc.exit_code if proc is not None else None
    elapsed = _elapsed_seconds(proc) if proc is not None else None
    if elapsed is None:
        elapsed = 0.0
    timeout_kind = _timeout_kind(termination_reason)
    timeout_message = _timeout_message(
        timeout_kind,
        total_timeout_seconds=float(meta.get("monitor_timeout_seconds") or 0.0),
        idle_timeout_seconds=float(meta.get("monitor_idle_timeout_seconds") or 0.0),
        elapsed_seconds=elapsed,
    )
    log_path = str(state.get("log_path") or meta.get("monitor_output_path") or "")
    capture = _capture_from_log(log_path)
    error = (
        state.get("message") if monitor_state in {"failed", "lost", "timeout"} else None
    )

    meta["monitor_state"] = monitor_state
    if exit_code is not None:
        meta["monitor_exit_code"] = exit_code
    meta["monitor_output_truncated"] = capture.truncated
    if log_path:
        meta["monitor_output_path"] = log_path
    meta["stopped_at"] = _utc_now_iso()
    if timeout_kind is not None:
        meta["monitor_timeout_kind"] = timeout_kind
        if timeout_message:
            meta["monitor_timeout_message"] = timeout_message
    write_agent_meta_atomic(
        artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )

    member_name = str(meta.get("name") or "")
    timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    response_path = save_chat_history(
        f"sase monitor start --command {meta.get('monitor_command')!r} "
        f"--reason {meta.get('monitor_reason')!r}",
        capture.retained_text(),
        "ace-run",
        agent=member_name,
        timestamp=timestamp,
        branch_or_workspace=meta.get("cl_name"),
        metadata_agent=member_name,
        metadata_model=meta.get("model"),
        metadata_llm_provider=meta.get("llm_provider"),
    )
    state["monitor_state"] = monitor_state
    state["monitor_exit_code"] = exit_code
    state["monitor_elapsed_seconds"] = elapsed
    state["monitor_timeout_kind"] = timeout_kind
    state["monitor_timeout_message"] = timeout_message
    state["monitor_error"] = error
    state["response_path"] = response_path
    state["monitor_meta"] = meta


def settle_monitor_followup(state: dict[str, Any]) -> None:
    """Launch or suppress ``--next`` and write the terminal family markers."""
    artifacts_dir = state.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        state["followup_outcome"] = None
        return
    meta = _read_meta(artifacts_dir)
    if state.get("monitor_meta"):
        meta.update(state["monitor_meta"])
    monitor_state = str(
        state.get("monitor_state") or meta.get("monitor_state") or "failed"
    )
    exit_code = state.get("monitor_exit_code")
    if not isinstance(exit_code, int):
        exit_code = meta.get("monitor_exit_code")
        exit_code = exit_code if isinstance(exit_code, int) else None
    elapsed = float(state.get("monitor_elapsed_seconds") or 0.0)
    timeout_kind = state.get("monitor_timeout_kind")
    if not isinstance(timeout_kind, str):
        timeout_kind = meta.get("monitor_timeout_kind")
        timeout_kind = timeout_kind if isinstance(timeout_kind, str) else None
    log_path = str(state.get("log_path") or meta.get("monitor_output_path") or "")
    capture = _capture_from_log(log_path)
    project_name = project_name_from_artifacts_dir(artifacts_dir)
    transfer_from_pid = _transfer_pid(state)

    if meta.get("monitor_followup_outcome"):
        state["followup_outcome"] = meta.get("monitor_followup_outcome")
    else:
        followup_error = settle_claim_and_followup(
            artifacts_dir,
            meta,
            monitor_state=monitor_state,  # type: ignore[arg-type]
            exit_code=exit_code,
            elapsed_seconds=elapsed,
            capture=capture,
            timeout_kind=timeout_kind,
            project_name=project_name,
            transfer_from_pid=transfer_from_pid,
            launch_followup=launch_followup_agent,
        )
        state["followup_error"] = followup_error
        state["followup_outcome"] = meta.get("monitor_followup_outcome")

    meta["monitor_settled"] = True
    write_agent_meta_atomic(
        artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )

    raw_stop = meta.get("monitor_stop_status")
    stop_status = clamp_monitor_status_or_default(
        raw_stop if isinstance(raw_stop, str) else None,
        default=DEFAULT_STOP_STATUS,
    )
    done_marker: dict[str, Any] = {
        "outcome": "monitored",
        "name": meta.get("name"),
        "cl_name": meta.get("cl_name"),
        "workspace_dir": meta.get("workspace_dir"),
        "workspace_num": meta.get("workspace_num"),
        "monitor_state": monitor_state,
        "monitor_exit_code": exit_code,
        "monitor_elapsed_seconds": elapsed,
        "status_label": stop_status,
        "response_path": state.get("response_path"),
    }
    if project_name:
        done_marker["project_file"] = get_project_file_path(project_name)
    error = state.get("monitor_error") or state.get("followup_error")
    if error:
        done_marker["error"] = error
    followup_error = state.get("followup_error")
    if followup_error:
        done_marker["monitor_followup_error"] = followup_error
    for key in (
        "monitor_followup_outcome",
        "monitor_followup_degraded_reason",
        "monitor_followup_prompt_path",
    ):
        if meta.get(key):
            done_marker[key] = meta[key]
    timeout_kind = state.get("monitor_timeout_kind")
    timeout_message = state.get("monitor_timeout_message")
    if timeout_kind:
        done_marker["monitor_timeout_kind"] = timeout_kind
        if timeout_message:
            done_marker["monitor_timeout_message"] = timeout_message
    write_done_marker_and_update_index(artifacts_dir, done_marker)
    finalize_monitor_workflow_state(artifacts_dir)
    touch_monitor_refresh_pulse(project_name)


def _capture_from_log(path: str | Path) -> OutputCapture:
    """Rebuild a bounded output view from the authoritative log file."""
    capture = OutputCapture()
    if not path:
        return capture
    try:
        data = Path(path).read_bytes()
    except OSError:
        return capture
    if data:
        capture.append_bytes(data)
    return capture


def _termination_reason(proc: Proc) -> str | None:
    result = proc.result
    if isinstance(result, dict):
        reason = result.get("termination_reason")
        if isinstance(reason, str) and reason:
            return reason
    return proc.stop_reason


def _monitor_state_from_reason(reason: str, *, status: str) -> MonitorState:
    if reason == "stop" or status == "killed":
        return "stopped"
    if reason in {"total-timeout", "idle-timeout"}:
        return "timeout"
    if reason in {"reboot", "supervisor-loss"}:
        return "lost"
    if status == "success" or reason == "success":
        return "completed"
    return "failed"


def _timeout_kind(reason: str) -> str | None:
    if reason == "total-timeout":
        return "total"
    if reason == "idle-timeout":
        return "idle"
    return None


def _timeout_message(
    timeout_kind: str | None,
    *,
    total_timeout_seconds: float,
    idle_timeout_seconds: float,
    elapsed_seconds: float,
) -> str | None:
    if timeout_kind == "idle":
        return f"no output for {_format_duration(idle_timeout_seconds)}"
    if timeout_kind == "total":
        elapsed = _format_duration(elapsed_seconds)
        total = _format_duration(total_timeout_seconds)
        return f"did not finish after {elapsed} of a {total} budget"
    return None


def _format_duration(seconds: float) -> str:
    if 0 < seconds < 1:
        return f"{seconds:g}s"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _elapsed_seconds(proc: Proc | None) -> float | None:
    if proc is None:
        return None
    start = _parse_timestamp(proc.started_at or proc.created_at)
    end = _parse_timestamp(proc.finished_at or proc.settled_at)
    if start is None:
        return None
    if end is None:
        end = datetime.now(UTC)
    return max(0.0, (end - start).total_seconds())


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _transfer_pid(state: dict[str, Any]) -> int | None:
    claim = state.get("workspace_claim")
    if isinstance(claim, dict):
        raw = claim.get("supervisor_pid")
        if isinstance(raw, int):
            return raw
    proc = get_proc(str(state.get("proc_id") or ""))
    return proc.pid if proc is not None else None


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "MONITOR_ARGV_PREFIX",
    "MONITOR_FOLLOWUP_KIND",
    "MONITOR_PROC_ORIGIN",
    "compile_monitor_argv",
    "monitor_proc_argv",
    "overlay_proc_on_monitor",
    "proc_shell_owns",
    "settle_monitor_artifacts",
    "settle_monitor_followup",
]
