"""Logs collection and packaging for sase.

Canonical log files live under ``~/.sase/logs/``. The path helpers re-exported
here are the single source of truth for those paths so every frontend (TUI,
CLI, web) reads the same files.
"""

from sase.logs.launch_log import (
    launch_failures_jsonl_path,
    launch_failures_log_path,
    log_launch_failure,
    tui_log_path,
)
from sase.logs.run_log import events_log_path, runs_log_path

__all__ = [
    "events_log_path",
    "launch_failures_jsonl_path",
    "launch_failures_log_path",
    "log_launch_failure",
    "runs_log_path",
    "tui_log_path",
]
