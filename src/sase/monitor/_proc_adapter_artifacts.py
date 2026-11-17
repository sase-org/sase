"""Persist monitor settlement state and diagnostic artifacts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.bead.epic_launch_handoff import publish_deferred_monitor_completion
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.continuation_capture import persist_monitor_result_best_effort
from sase.history.chat import save_chat_history
from sase.procs.store import get_proc

from .diagnostics import (
    assemble_diagnostic_manifest,
    diagnostic_manifest_path,
    freeze_retained_log_metadata,
    retained_log_metadata_path,
)
from ._proc_adapter_helpers import (
    capture_from_log,
    command_ended_at,
    elapsed_seconds,
    read_meta,
)
from .logs import monitor_log_path
from .models import MonitorState
from .settlement import project_name_from_artifacts_dir

_SAVE_CHAT_HISTORY_FAIL_ENV = "SASE_PROC_SETTLEMENT_FAIL_SAVE_CHAT_HISTORY"
_INCIDENT_IMPORT_NAME = "legacy_" + "x" + "prompt_syntax_enabled"


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


def settle_monitor_artifacts(state: dict[str, Any]) -> None:
    """Write agent-session presentation for a monitor whose command is gone."""
    artifacts_dir = state.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return
    meta = read_meta(artifacts_dir)
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
    stopped_at = command_ended_at(state, meta=meta, proc=proc)
    elapsed = elapsed_seconds(proc, ended_at=stopped_at) if proc is not None else None
    if elapsed is None:
        elapsed = 0.0
    monitor_timeout_kind = _timeout_kind(termination_reason)
    monitor_timeout_message = _timeout_message(
        monitor_timeout_kind,
        total_timeout_seconds=float(meta.get("monitor_timeout_seconds") or 0.0),
        idle_timeout_seconds=float(meta.get("monitor_idle_timeout_seconds") or 0.0),
        elapsed_seconds=elapsed,
    )
    log_path = str(state.get("log_path") or meta.get("monitor_output_path") or "")
    capture = capture_from_log(log_path)
    error = (
        state.get("message") if monitor_state in {"failed", "lost", "timeout"} else None
    )

    meta["monitor_state"] = monitor_state
    if exit_code is not None:
        meta["monitor_exit_code"] = exit_code
    meta["monitor_output_truncated"] = capture.truncated
    if log_path:
        meta["monitor_output_path"] = log_path
    if monitor_timeout_kind is not None:
        meta["monitor_timeout_kind"] = monitor_timeout_kind
        if monitor_timeout_message:
            meta["monitor_timeout_message"] = monitor_timeout_message
    monitor_id = str(meta.get("monitor_id") or state.get("proc_id") or "monitor")
    diagnostic_manifest = assemble_diagnostic_manifest(
        artifacts_dir,
        monitor_id=monitor_id,
        complete=monitor_state == "completed",
    )
    retained_log = freeze_retained_log_metadata(
        artifacts_dir,
        output_path=Path(log_path) if log_path else monitor_log_path(artifacts_dir),
        monitor_id=monitor_id,
        retention=None,
    )
    meta["monitor_diagnostic_manifest_path"] = str(
        diagnostic_manifest_path(artifacts_dir)
    )
    meta["monitor_diagnostic_manifest_ref"] = diagnostic_manifest.get("manifest_ref")
    meta["monitor_retained_log_metadata_path"] = str(
        retained_log_metadata_path(artifacts_dir)
    )
    meta["monitor_retained_log_ref"] = retained_log.get("log_ref")
    project_name = project_name_from_artifacts_dir(artifacts_dir)
    persist_monitor_result_best_effort(
        artifacts_dir=artifacts_dir,
        meta=meta,
        monitor_state=monitor_state,
        exit_code=exit_code,
        elapsed_seconds=elapsed,
        stopped_at=stopped_at,
        diagnostic_manifest=diagnostic_manifest,
        retained_log=retained_log,
        timeout_kind=monitor_timeout_kind,
        project_name=project_name,
        update_meta=False,
    )
    persisted_meta = dict(meta)
    persisted_meta.pop("stopped_at", None)
    write_agent_meta_atomic(
        artifacts_dir,
        persisted_meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )
    meta["stopped_at"] = stopped_at
    _maybe_fail_save_chat_history()

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
    state["monitor_timeout_kind"] = monitor_timeout_kind
    state["monitor_timeout_message"] = monitor_timeout_message
    state["monitor_error"] = error
    state["response_path"] = response_path
    state["monitor_meta"] = meta


def _maybe_fail_save_chat_history() -> None:
    """Inject the incident ImportError after the monitor result is persisted."""
    triggered = bool(os.environ.pop(_SAVE_CHAT_HISTORY_FAIL_ENV, None))
    home = os.environ.get("SASE_HOME")
    marker = Path(home) / ".fail-save-chat-history" if home else None
    if marker is not None and marker.is_file():
        triggered = True
        try:
            marker.unlink()
        except OSError:
            pass
    if not triggered:
        return
    raise ImportError(f"cannot import name '{_INCIDENT_IMPORT_NAME}'")
