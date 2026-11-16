"""Durable TUI telemetry logs.

These files are intentionally small JSONL append-only diagnostics under
``~/.sase/logs``. They are for post-mortem forensics, so writers must never
raise back into the TUI or launch paths.
"""

from __future__ import annotations

import logging
import json
import os
import time
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir
from sase.logs._bounded import (
    DEFAULT_MAX_BYTES,
    append_encoded_line_locked,
    append_jsonl_record,
    encode_jsonl_record,
    log_file_lock,
    max_bytes_from_env,
)

log = logging.getLogger(__name__)

LOGS_DIR: str | None = None
TUI_STALLS_JSONL: str | None = None
TUI_GIT_OPS_JSONL: str | None = None
TUI_LAUNCH_TIMING_JSONL: str | None = None
TUI_EXTERNAL_TOOLS_JSONL: str | None = None
TUI_AGENT_LOADS_JSONL: str | None = None
TUI_STARTUP_JSONL: str | None = None

ENV_STALL_PATH = "SASE_TUI_STALL_PATH"
ENV_GIT_OPS_PATH = "SASE_TUI_GIT_OPS_PATH"
ENV_LAUNCH_TIMING_PATH = "SASE_TUI_LAUNCH_TIMING_PATH"
ENV_EXTERNAL_TOOLS_PATH = "SASE_TUI_EXTERNAL_TOOLS_PATH"
ENV_AGENT_LOADS_PATH = "SASE_TUI_AGENT_LOADS_PATH"
ENV_STARTUP_PATH = "SASE_TUI_STARTUP_PATH"
ENV_MAX_BYTES = "SASE_TUI_TELEMETRY_MAX_BYTES"
STALL_RETENTION_SECONDS = 48 * 60 * 60
STALL_PRUNE_INTERVAL_SECONDS = 60 * 60
_last_stalls_prune_bucket: tuple[Path, int] | None = None


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


def tui_startup_jsonl_path() -> Path:
    """Canonical path of the one-record-per-session ACE startup JSONL log."""
    return Path(
        TUI_STARTUP_JSONL
        or os.environ.get(ENV_STARTUP_PATH)
        or os.path.join(_logs_dir(), "tui_startup.jsonl")
    )


def log_tui_stall(record: dict[str, Any]) -> None:
    """Append one event-loop record, retaining at least the latest 24 hours."""
    path = tui_stalls_jsonl_path()
    try:
        encoded = encode_jsonl_record(record, json_default=str)
        now = time.time()
        prune_bucket = int(now // STALL_PRUNE_INTERVAL_SECONDS)
        prune_key = (path, prune_bucket)
        with log_file_lock(path):
            global _last_stalls_prune_bucket
            if _last_stalls_prune_bucket != prune_key:
                cutoff = now - STALL_RETENTION_SECONDS
                try:
                    lines = path.read_bytes().splitlines(keepends=True)
                except FileNotFoundError:
                    lines = []
                retained: list[bytes] = []
                for line in lines:
                    try:
                        row = json.loads(line)
                        timestamp = float(row.get("ts"))
                    except (
                        ValueError,
                        TypeError,
                        AttributeError,
                        json.JSONDecodeError,
                    ):
                        retained.append(line if line.endswith(b"\n") else line + b"\n")
                        continue
                    if timestamp >= cutoff:
                        retained.append(line if line.endswith(b"\n") else line + b"\n")
                path.write_bytes(b"".join(retained))
                _last_stalls_prune_bucket = prune_key
            append_encoded_line_locked(path, encoded, max_bytes=0)
    except Exception:
        log.debug("TUI telemetry write failed for %s", path, exc_info=True)


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


def log_tui_startup(record: dict[str, Any]) -> None:
    """Append one per-session ACE startup timing record."""
    _append_jsonl(tui_startup_jsonl_path(), record)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    try:
        append_jsonl_record(
            path,
            record,
            max_bytes=_max_bytes(),
            json_default=str,
        )
    except Exception:
        log.debug("TUI telemetry write failed for %s", path, exc_info=True)


def _max_bytes() -> int:
    return max_bytes_from_env(ENV_MAX_BYTES, DEFAULT_MAX_BYTES)
