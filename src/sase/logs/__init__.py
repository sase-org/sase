"""Logs collection and packaging for sase.

Canonical log files live under ``~/.sase/logs/``. The path helpers re-exported
here are the single source of truth for those paths so every frontend (TUI,
CLI, web) reads the same files.
"""

from sase.logs.error_registry import (
    RegisteredError,
    clear_registered_errors,
    error_anchor,
    last_registered_error,
    new_error_id,
    register_error,
)
from sase.logs.launch_log import (
    launch_failures_jsonl_path,
    launch_failures_log_path,
    log_launch_failure,
    tui_log_path,
)
from sase.logs.project_creation_log import (
    log_project_creation,
    project_creation_jsonl_path,
    project_creation_log_path,
)
from sase.logs.run_log import events_log_path, runs_log_path
from sase.logs.tui_telemetry import (
    log_tui_agent_load,
    log_tui_external_tool_wait,
    log_tui_git_operation,
    log_tui_launch_timing,
    log_tui_stall,
    log_tui_startup,
    tui_agent_loads_jsonl_path,
    tui_external_tools_jsonl_path,
    tui_git_ops_jsonl_path,
    tui_launch_timing_jsonl_path,
    tui_stalls_jsonl_path,
    tui_startup_jsonl_path,
)
from sase.logs.toast_log import (
    TOAST_HISTORY_LIMIT,
    ToastRecord,
    ToastSession,
    current_toast_session,
    flush_toasts,
    read_recent_toasts,
    record_toast,
    tui_toasts_jsonl_path,
)

__all__ = [
    "RegisteredError",
    "clear_registered_errors",
    "error_anchor",
    "events_log_path",
    "last_registered_error",
    "launch_failures_jsonl_path",
    "launch_failures_log_path",
    "log_launch_failure",
    "new_error_id",
    "register_error",
    "log_project_creation",
    "project_creation_jsonl_path",
    "project_creation_log_path",
    "runs_log_path",
    "log_tui_external_tool_wait",
    "log_tui_agent_load",
    "log_tui_git_operation",
    "log_tui_launch_timing",
    "log_tui_stall",
    "log_tui_startup",
    "TOAST_HISTORY_LIMIT",
    "ToastRecord",
    "ToastSession",
    "current_toast_session",
    "tui_agent_loads_jsonl_path",
    "tui_external_tools_jsonl_path",
    "tui_git_ops_jsonl_path",
    "tui_launch_timing_jsonl_path",
    "tui_stalls_jsonl_path",
    "tui_startup_jsonl_path",
    "flush_toasts",
    "read_recent_toasts",
    "record_toast",
    "tui_toasts_jsonl_path",
    "tui_log_path",
]
