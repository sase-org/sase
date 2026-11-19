"""Durable TUI telemetry logs.

These files are intentionally small JSONL append-only diagnostics under
``~/.sase/logs``. They are for post-mortem forensics, so writers must never
raise back into the TUI or launch paths.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir
from sase.logs._bounded import (
    DEFAULT_MAX_BYTES,
    append_jsonl_record,
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
ENV_STALL_MAX_BYTES = "SASE_TUI_STALL_MAX_BYTES"
# ``tui_stalls.jsonl`` is the acceptance metric for TUI freeze work, so it keeps
# at least 48 hours of rows instead of the 2 MiB sibling cap. Size rotation
# keeps one ``.1`` segment, and right after a rotation only that segment holds
# history, so one segment alone must cover 48 hours. Measured on 2026-11-19
# with slimmed rows (no sub-0.5 s young-generation pause rows, depth-capped
# hitch stacks): athena writes about 19.8 MiB per 48 hours and apollo about
# 11.5 MiB. 24 MiB keeps roughly 20% headroom over athena; the log plus its
# ``.1`` segment never exceed 48 MiB on disk.
STALL_MAX_BYTES = 24 * 1024 * 1024


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
    """Append one stall-log row; size rotation retains at least 48 hours.

    The row goes through the shared bounded-append helper: one ``O_APPEND``
    write under the sibling lock, rotating to ``.1`` before the active file
    would exceed :data:`STALL_MAX_BYTES`. No writer ever parses or rewrites
    the log in place.
    """
    _append_jsonl(tui_stalls_jsonl_path(), record, max_bytes=_stall_max_bytes())


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


def _append_jsonl(
    path: Path,
    record: dict[str, Any],
    *,
    max_bytes: int | None = None,
) -> None:
    try:
        append_jsonl_record(
            path,
            record,
            max_bytes=_max_bytes() if max_bytes is None else max_bytes,
            json_default=str,
        )
    except Exception:
        log.debug("TUI telemetry write failed for %s", path, exc_info=True)


def _max_bytes() -> int:
    return max_bytes_from_env(ENV_MAX_BYTES, DEFAULT_MAX_BYTES)


def _stall_max_bytes() -> int:
    return max_bytes_from_env(ENV_STALL_MAX_BYTES, STALL_MAX_BYTES)
