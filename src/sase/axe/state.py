"""Disk state management for sase axe scheduler.

This module handles all state persistence for the axe scheduler, enabling
sase ace to monitor and control axe processes via the TUI.

Includes both the flat scheduler state (legacy) and per-lumberjack state
directories used by the new lumberjack architecture.

Live path accessors and the shared low-level JSON / log helpers live in this
module. Axe paths are resolved at call time so changes to ``SASE_HOME`` or
``HOME`` take effect even when this module was imported earlier. The
dataclasses and higher-level read/write helpers live in sibling ``_state_*``
modules and are re-exported below.
"""

import json
from datetime import datetime
from pathlib import Path

from sase.core.paths import sase_subdir
from sase.core.time import get_timezone


def axe_state_dir() -> Path:
    """Return the current axe state directory."""
    return sase_subdir("axe")


def jack_state_dir() -> Path:
    """Return the current per-lumberjack state directory."""
    return axe_state_dir() / "lumberjacks"


def shared_state_dir() -> Path:
    """Return the current shared cross-process state directory."""
    return axe_state_dir() / "shared"


def axe_output_log_path() -> Path:
    """Return the current axe output log path."""
    return axe_state_dir() / "logs" / "output.log"


def ensure_state_dir() -> None:
    """Ensure state directory exists."""
    axe_state_dir().mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, data: dict | list) -> None:
    """Write JSON atomically using temp file + rename.

    Args:
        path: Target file path.
        data: Dictionary or list to write as JSON.
    """
    ensure_state_dir()
    temp_path = path.with_suffix(".tmp")
    try:
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2)
        temp_path.rename(path)
    except OSError:
        # Clean up temp file if rename failed
        try:
            temp_path.unlink()
        except OSError:
            pass


def read_json(path: Path) -> dict | None:
    """Read JSON file safely.

    Args:
        path: File path to read.

    Returns:
        Parsed JSON dict, or None if file doesn't exist or is invalid.
    """
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def read_tail_seek(log_file: Path, lines: int) -> str:
    """Read the last N lines of a file by seeking from the end.

    O(tail size), not O(file size). Safe on multi-GB log files where a
    deque over the whole file would burn minutes of I/O.
    """
    # Start with a 64KB window and double until we have enough newlines or
    # we've read the entire file.
    block_size = 64 * 1024
    try:
        with open(log_file, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            data = b""
            while len(data) < file_size:
                to_read = min(block_size, file_size - len(data))
                f.seek(file_size - len(data) - to_read)
                data = f.read(to_read) + data
                if data.count(b"\n") > lines:
                    break
                block_size *= 2
        text = data.decode("utf-8", errors="replace")
        tail_lines = text.splitlines(keepends=True)[-lines:]
        return "".join(tail_lines)
    except OSError:
        return ""


def get_timestamp() -> str:
    """Get current timestamp in ISO format with timezone.

    Returns:
        ISO formatted timestamp string.
    """
    return datetime.now(get_timezone()).isoformat()


# Section modules access the functions above via ``import sase.axe.state as
# _state`` and call them at runtime, which is why these re-export imports go at
# the bottom: section modules are only loaded once the names above are bound on
# this module.
from sase.axe._state_chops import (  # noqa: E402
    ACTIVE_CHOP_RUN_STATUSES,
    MAX_CHOP_RUN_HISTORY,
    ChopRunEntry,
    ChopRunSource,
    ChopRunStatus,
    append_chop_run_output,
    chop_index_path,
    chop_run_context_path,
    chop_run_log_path,
    chop_run_meta_path,
    chop_run_result_path,
    chop_runs_dir,
    ensure_chop_dirs,
    finish_chop_run,
    generate_chop_run_id,
    read_chop_run,
    read_chop_run_index,
    read_chop_run_log_tail,
    start_chop_run,
    update_chop_run_pid,
    write_chop_run,
)
from sase.axe._state_lumberjack import (  # noqa: E402
    DEFAULT_LUMBERJACK_LOG_MAX_BYTES,
    DEFAULT_LUMBERJACK_LOG_TEMP_MAX_AGE_SECONDS,
    LumberjackMetrics,
    LumberjackStatus,
    append_bounded_log,
    append_lumberjack_log,
    clear_lumberjack_output_log,
    ensure_lumberjack_dirs,
    ensure_shared_dir,
    list_lumberjack_names,
    lumberjack_log_path,
    lumberjack_state_dir,
    read_chop_timestamps,
    read_lumberjack_log_tail,
    read_lumberjack_metrics,
    read_lumberjack_pid,
    read_lumberjack_status,
    reap_stale_log_rotation_temps,
    remove_lumberjack_pid,
    write_chop_timestamps,
    write_lumberjack_metrics,
    write_lumberjack_pid,
    write_lumberjack_status,
)
from sase.axe._state_scheduler import (  # noqa: E402
    AxeMetrics,
    AxeStatus,
    CycleResult,
    append_error,
    read_cycle_result,
    read_errors,
    read_last_error_digest_ts,
    read_metrics,
    read_output_log_tail,
    read_pid_file,
    read_status,
    remove_pid_file,
    write_cycle_result,
    write_last_error_digest_ts,
)

__all__ = [
    "ACTIVE_CHOP_RUN_STATUSES",
    "AxeMetrics",
    "AxeStatus",
    "ChopRunEntry",
    "ChopRunSource",
    "ChopRunStatus",
    "CycleResult",
    "DEFAULT_LUMBERJACK_LOG_MAX_BYTES",
    "DEFAULT_LUMBERJACK_LOG_TEMP_MAX_AGE_SECONDS",
    "LumberjackMetrics",
    "LumberjackStatus",
    "MAX_CHOP_RUN_HISTORY",
    "append_bounded_log",
    "append_chop_run_output",
    "append_error",
    "append_lumberjack_log",
    "atomic_write_json",
    "axe_output_log_path",
    "axe_state_dir",
    "chop_index_path",
    "chop_run_context_path",
    "chop_run_log_path",
    "chop_run_meta_path",
    "chop_run_result_path",
    "chop_runs_dir",
    "clear_lumberjack_output_log",
    "ensure_chop_dirs",
    "ensure_lumberjack_dirs",
    "ensure_shared_dir",
    "ensure_state_dir",
    "finish_chop_run",
    "generate_chop_run_id",
    "get_timestamp",
    "jack_state_dir",
    "list_lumberjack_names",
    "lumberjack_log_path",
    "lumberjack_state_dir",
    "read_chop_run",
    "read_chop_run_index",
    "read_chop_run_log_tail",
    "read_chop_timestamps",
    "read_cycle_result",
    "read_errors",
    "read_json",
    "read_last_error_digest_ts",
    "read_lumberjack_log_tail",
    "read_lumberjack_metrics",
    "read_lumberjack_pid",
    "read_lumberjack_status",
    "read_metrics",
    "read_output_log_tail",
    "read_pid_file",
    "read_status",
    "read_tail_seek",
    "reap_stale_log_rotation_temps",
    "remove_lumberjack_pid",
    "remove_pid_file",
    "shared_state_dir",
    "start_chop_run",
    "update_chop_run_pid",
    "write_chop_run",
    "write_chop_timestamps",
    "write_cycle_result",
    "write_last_error_digest_ts",
    "write_lumberjack_metrics",
    "write_lumberjack_pid",
    "write_lumberjack_status",
]
