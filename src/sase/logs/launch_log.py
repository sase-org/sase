"""Durable launch-failure logging.

Every agent launch / fan-out / multi-prompt / repeat / bulk / workflow / chop
failure is written, with full context and traceback, to two canonical files
under ``~/.sase/logs/``:

- ``launch_failures.jsonl`` — one structured JSON record per failure (machine
  readable; what any frontend reads).
- ``launch_failures.log`` — a formatted, human-readable block per failure
  (timestamp header, kind, display name, project, workspace, exception
  class+message, full traceback, prompt preview, extra context).

This mirrors :mod:`sase.logs.run_log` conventions exactly: ``fcntl``-locked
append, ``sase_subdir("logs")`` for the canonical directory, and module-level
path overrides so tests can redirect the writers.

The cross-frontend contract is the file format and the paths exported here;
see ``sdd/epics/202606/log_panel.md`` for the deliberate decision to keep this
logging in Python's ``sase.logs`` package rather than the Rust core.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir
from sase.core.time import get_timezone
from sase.logs.error_registry import error_anchor, new_error_id

log = logging.getLogger(__name__)

# Failure kinds written by the TUI launch handlers. Kept as documentation of
# the contract; unknown kinds are still logged (logging must never reject).
LAUNCH_FAILURE_KINDS: frozenset[str] = frozenset(
    {
        "single",
        "fanout",
        "multi_prompt",
        "repeat",
        "bulk",
        "workflow",
        "chop",
    }
)

# Module-level path overrides for tests (same pattern as ``run_log``).
LOGS_DIR: str | None = None
LAUNCH_FAILURES_LOG: str | None = None
LAUNCH_FAILURES_JSONL: str | None = None
TUI_LOG: str | None = None

_PROMPT_PREVIEW_LIMIT = 200


def _logs_dir() -> str:
    return LOGS_DIR or str(sase_subdir("logs"))


def launch_failures_log_path() -> Path:
    """Canonical path of the human-readable launch-failure log."""
    return Path(LAUNCH_FAILURES_LOG or os.path.join(_logs_dir(), "launch_failures.log"))


def launch_failures_jsonl_path() -> Path:
    """Canonical path of the structured launch-failure JSONL log."""
    return Path(
        LAUNCH_FAILURES_JSONL or os.path.join(_logs_dir(), "launch_failures.jsonl")
    )


def tui_log_path() -> Path:
    """Canonical path of the catch-all TUI diagnostics log."""
    return Path(TUI_LOG or os.path.join(_logs_dir(), "tui.log"))


def _append_locked(path: Path, text: str) -> None:
    """Append *text* to *path* with an exclusive file lock (creates dirs)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(text)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def log_launch_failure(
    *,
    kind: str,
    display_name: str,
    exc: BaseException,
    project: str | None = None,
    workspace_num: int | None = None,
    prompt_preview: str | None = None,
    error_id: str | None = None,
    **context: Any,
) -> str:
    """Durably record a launch failure to both canonical launch-failure logs.

    Appends a structured record to ``launch_failures.jsonl`` AND a formatted,
    human-readable block to ``launch_failures.log``. Never raises: any I/O
    error is swallowed (and surfaced through the module logger, which the TUI
    routes to ``tui.log``) so logging a failure can never mask or escalate the
    original launch error. Returns the ``error_id`` used (minted when the
    caller passed none), even if the write failed.

    Args:
        kind: One of :data:`LAUNCH_FAILURE_KINDS` (``"single"``, ``"fanout"``,
            ``"multi_prompt"``, ``"repeat"``, ``"bulk"``, ``"workflow"``,
            ``"chop"``).
        display_name: Human-facing name of the launch (PR/agent name).
        exc: The exception that caused the failure (traceback captured from it).
        project: Originating project name, if known.
        workspace_num: Workspace number, if allocated.
        prompt_preview: Submitted prompt text (truncated when stored).
        error_id: Stable id stamped on the JSONL record and human header. Minted
            when omitted.
        **context: Extra structured context (``fanout_kind``, ``slot_count``,
            ``workflow_name``, ``chop``, ``vcs_ref``, ...). ``None`` values are
            dropped.
    """
    used_id = new_error_id() if error_id is None else error_id
    try:
        _write_launch_failure(
            kind=kind,
            display_name=display_name,
            exc=exc,
            project=project,
            workspace_num=workspace_num,
            prompt_preview=prompt_preview,
            error_id=used_id,
            context=context,
        )
    except Exception:  # pragma: no cover - logging must never break a launch
        log.warning("Failed to write launch-failure log", exc_info=True)
    return used_id


def _write_launch_failure(
    *,
    kind: str,
    display_name: str,
    exc: BaseException,
    project: str | None,
    workspace_num: int | None,
    prompt_preview: str | None,
    error_id: str,
    context: dict[str, Any],
) -> None:
    now = datetime.now(get_timezone())
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    exc_type = type(exc).__name__
    exc_message = str(exc)
    extra = {key: value for key, value in context.items() if value is not None}
    if prompt_preview:
        prompt_preview = prompt_preview[:_PROMPT_PREVIEW_LIMIT]

    _append_jsonl_record(
        now=now,
        kind=kind,
        display_name=display_name,
        exc_type=exc_type,
        exc_message=exc_message,
        traceback_text=tb,
        project=project,
        workspace_num=workspace_num,
        prompt_preview=prompt_preview,
        error_id=error_id,
        extra=extra,
    )
    _append_human_block(
        now=now,
        kind=kind,
        display_name=display_name,
        exc_type=exc_type,
        exc_message=exc_message,
        traceback_text=tb,
        project=project,
        workspace_num=workspace_num,
        prompt_preview=prompt_preview,
        error_id=error_id,
        extra=extra,
    )


def _append_jsonl_record(
    *,
    now: datetime,
    kind: str,
    display_name: str,
    exc_type: str,
    exc_message: str,
    traceback_text: str,
    project: str | None,
    workspace_num: int | None,
    prompt_preview: str | None,
    error_id: str,
    extra: dict[str, Any],
) -> None:
    record: dict[str, Any] = {
        "timestamp": now.strftime("%y%m%d_%H%M%S"),
        "error_id": error_id,
        "kind": kind,
        "display_name": display_name,
        "exc_type": exc_type,
        "exc_message": exc_message,
    }
    if project is not None:
        record["project"] = project
    if workspace_num is not None:
        record["workspace_num"] = workspace_num
    if prompt_preview:
        record["prompt_preview"] = prompt_preview
    record.update(extra)
    record["traceback"] = traceback_text
    _append_locked(launch_failures_jsonl_path(), json.dumps(record, default=str) + "\n")


def _append_human_block(
    *,
    now: datetime,
    kind: str,
    display_name: str,
    exc_type: str,
    exc_message: str,
    traceback_text: str,
    project: str | None,
    workspace_num: int | None,
    prompt_preview: str | None,
    error_id: str,
    extra: dict[str, Any],
) -> None:
    header_ts = now.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    lines = [
        "=" * 72,
        f"[{header_ts}] {kind} launch failure: {display_name}  "
        f"{error_anchor(error_id)}",
        f"  error: {exc_type}: {exc_message}",
    ]
    if project is not None:
        lines.append(f"  project: {project}")
    if workspace_num is not None:
        lines.append(f"  workspace: #{workspace_num}")
    for key, value in extra.items():
        lines.append(f"  {key}: {value}")
    if prompt_preview:
        lines.append(f"  prompt: {prompt_preview}")
    lines.append("")
    lines.append("  traceback:")
    lines.extend(
        "    " + tb_line for tb_line in traceback_text.rstrip("\n").splitlines()
    )
    lines.append("")
    _append_locked(launch_failures_log_path(), "\n".join(lines) + "\n")
