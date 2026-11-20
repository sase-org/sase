"""Scheduled ToolRun retention and empty-dir cleanup for housekeeping.

``clutter_reapers`` adds further owner steps to the same chop; this module
owns the interval gate and the ToolRun pass. It does not add a second
tool-run policy.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.config.tools import (
    ToolRunsConfigError,
    get_tool_run_housekeeping_interval_seconds,
)
from sase.core.disk_footprint_models import DiskReapStep
from sase.core.disk_footprint_reap_tool_run import (
    EmptyLogDirSweep,
    remove_empty_tool_run_log_dirs,
    tool_run_reap_step,
)
from sase.core.paths import sase_home
from sase.notification_gates.durability import atomic_write_json

_STAMP_SCHEMA_VERSION = 1
_STAMP_NAME = "state_retention.json"


@dataclass(frozen=True)
class StateRetentionOutcome:
    """One scheduled state-retention pass."""

    owner_applied: bool
    owner_skipped: bool
    owner_step: DiskReapStep | None
    empty_dirs: EmptyLogDirSweep
    interval_seconds: int
    errors: tuple[str, ...]


def _state_retention_stamp_path() -> Path:
    """Return the interval stamp for the scheduled ToolRun retention pass."""

    return sase_home() / "axe" / _STAMP_NAME


def run_state_retention(
    *,
    now: float | None = None,
    interval_seconds: int | None = None,
    stamp_path: Path | None = None,
    apply_empty_dirs: bool = True,
) -> StateRetentionOutcome:
    """Apply ToolRun retention at most once per interval, then sweep empty dirs."""

    moment = time.time() if now is None else now
    errors: list[str] = []
    try:
        interval = (
            get_tool_run_housekeeping_interval_seconds()
            if interval_seconds is None
            else interval_seconds
        )
    except ToolRunsConfigError as exc:
        errors.append(str(exc))
        interval = 0
    stamp = stamp_path if stamp_path is not None else _state_retention_stamp_path()
    last_run = _read_stamp(stamp)
    due = last_run is None or interval <= 0 or (moment - last_run) >= interval
    owner_step: DiskReapStep | None = None
    owner_applied = False
    owner_skipped = not due
    if due:
        owner_step = tool_run_reap_step(apply=True)
        owner_applied = owner_step.mode != "blocked"
        if owner_step.owner_error:
            errors.append(owner_step.owner_error)
        if owner_step.mode == "blocked":
            errors.append(owner_step.summary)
        else:
            _write_stamp(stamp, moment)
    if owner_applied and owner_step is not None:
        details = owner_step.details or {}
        empty_dirs = EmptyLogDirSweep(
            scanned=int(details.get("empty_dirs_scanned") or 0),
            selected=int(details.get("empty_dirs_selected") or 0),
            removed=int(details.get("empty_dirs_removed") or 0),
            errors=(),
            paths=tuple(str(path) for path in (details.get("empty_dirs") or ())),
        )
    else:
        empty_dirs = remove_empty_tool_run_log_dirs(apply=apply_empty_dirs)
        errors.extend(empty_dirs.errors)
    return StateRetentionOutcome(
        owner_applied=owner_applied,
        owner_skipped=owner_skipped,
        owner_step=owner_step,
        empty_dirs=empty_dirs,
        interval_seconds=interval,
        errors=tuple(errors),
    )


def outcome_summary_fields(outcome: StateRetentionOutcome) -> dict[str, Any]:
    """Return chop summary counters for one state-retention pass."""

    step = outcome.owner_step
    details = (step.details if step is not None else None) or {}
    return {
        "owner_applied": int(outcome.owner_applied),
        "owner_skipped": int(outcome.owner_skipped),
        "summary_rows": int(details.get("summary_rows") or 0),
        "detail_rows": int(details.get("detail_rows") or 0),
        "removed_files": int(details.get("removed_files") or 0),
        "empty_dirs_scanned": outcome.empty_dirs.scanned,
        "empty_dirs_removed": outcome.empty_dirs.removed,
        "protected_unsettled": int(details.get("protected_unsettled") or 0),
        "errors": len(outcome.errors),
        "interval_seconds": outcome.interval_seconds,
    }


def _read_stamp(path: Path) -> float | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("last_tool_run_retention_ts")
    if not isinstance(raw, (int, float, str)):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _write_stamp(path: Path, moment: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {
            "schema_version": _STAMP_SCHEMA_VERSION,
            "last_tool_run_retention_ts": moment,
        },
    )
