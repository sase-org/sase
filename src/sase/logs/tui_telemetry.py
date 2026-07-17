"""Durable TUI telemetry logs.

These files are intentionally small JSONL append-only diagnostics under
``~/.sase/logs``. They are for post-mortem forensics, so writers must never
raise back into the TUI or launch paths.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir

log = logging.getLogger(__name__)

LOGS_DIR: str | None = None
TUI_STALLS_JSONL: str | None = None
TUI_GIT_OPS_JSONL: str | None = None
TUI_LAUNCH_TIMING_JSONL: str | None = None
TUI_EXTERNAL_TOOLS_JSONL: str | None = None
TUI_AGENT_LOADS_JSONL: str | None = None

ENV_STALL_PATH = "SASE_TUI_STALL_PATH"
ENV_GIT_OPS_PATH = "SASE_TUI_GIT_OPS_PATH"
ENV_LAUNCH_TIMING_PATH = "SASE_TUI_LAUNCH_TIMING_PATH"
ENV_EXTERNAL_TOOLS_PATH = "SASE_TUI_EXTERNAL_TOOLS_PATH"
ENV_AGENT_LOADS_PATH = "SASE_TUI_AGENT_LOADS_PATH"
ENV_MAX_BYTES = "SASE_TUI_TELEMETRY_MAX_BYTES"

DEFAULT_MAX_BYTES = 2_000_000


def _logs_dir() -> str:
    return LOGS_DIR or str(sase_subdir("logs"))


def tui_stalls_jsonl_path() -> Path:
    """Canonical path of the TUI event-loop stall JSONL log."""
    return Path(
        TUI_STALLS_JSONL
        or os.environ.get(ENV_STALL_PATH)
        or os.path.join(_logs_dir(), "tui_stalls.jsonl")
    )


def tui_git_ops_jsonl_path() -> Path:
    """Canonical path of TUI-adjacent git operation timing JSONL."""
    return Path(
        TUI_GIT_OPS_JSONL
        or os.environ.get(ENV_GIT_OPS_PATH)
        or os.path.join(_logs_dir(), "tui_git_ops.jsonl")
    )


def tui_launch_timing_jsonl_path() -> Path:
    """Canonical path of agent-launch timing summary JSONL."""
    return Path(
        TUI_LAUNCH_TIMING_JSONL
        or os.environ.get(ENV_LAUNCH_TIMING_PATH)
        or os.path.join(_logs_dir(), "tui_launch_timing.jsonl")
    )


def tui_external_tools_jsonl_path() -> Path:
    """Canonical path of the intentional external-tool wait JSONL log.

    Records SASE-owned terminal handoffs (editor / artifact-viewer launches
    under ``App.suspend()``) so they are not conflated with the genuine
    event-loop stalls in ``tui_stalls.jsonl``.
    """
    return Path(
        TUI_EXTERNAL_TOOLS_JSONL
        or os.environ.get(ENV_EXTERNAL_TOOLS_PATH)
        or os.path.join(_logs_dir(), "tui_external_tools.jsonl")
    )


def tui_agent_loads_jsonl_path() -> Path:
    """Canonical path of slow Agents-tab loader timing records."""
    return Path(
        TUI_AGENT_LOADS_JSONL
        or os.environ.get(ENV_AGENT_LOADS_PATH)
        or os.path.join(_logs_dir(), "tui_agent_loads.jsonl")
    )


def log_tui_stall(record: dict[str, Any]) -> None:
    """Append one event-loop stall record."""
    _append_jsonl(tui_stalls_jsonl_path(), record)


def log_tui_git_operation(record: dict[str, Any]) -> None:
    """Append one git operation timing or timeout record."""
    _append_jsonl(tui_git_ops_jsonl_path(), record)


def log_tui_launch_timing(record: dict[str, Any]) -> None:
    """Append one launch timing summary record."""
    _append_jsonl(tui_launch_timing_jsonl_path(), record)


def log_tui_external_tool_wait(record: dict[str, Any]) -> None:
    """Append one intentional external-tool terminal-handoff wait record."""
    _append_jsonl(tui_external_tools_jsonl_path(), record)


def log_tui_agent_load(record: dict[str, Any]) -> None:
    """Append one slow Agents-tab loader timing record."""
    _append_jsonl(tui_agent_loads_jsonl_path(), record)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(path, _max_bytes())
        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(record, default=str) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        log.debug("TUI telemetry write failed for %s", path, exc_info=True)


def _max_bytes() -> int:
    raw = os.environ.get(ENV_MAX_BYTES)
    if raw is None:
        return DEFAULT_MAX_BYTES
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_MAX_BYTES


def _rotate_if_needed(path: Path, max_bytes: int) -> None:
    if max_bytes <= 0:
        return
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return
        rotated = path.with_name(f"{path.name}.1")
        try:
            rotated.unlink()
        except FileNotFoundError:
            pass
        path.replace(rotated)
    except OSError:
        log.debug("TUI telemetry rotation failed for %s", path, exc_info=True)
