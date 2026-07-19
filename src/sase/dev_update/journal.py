"""Persistent JSONL journal for editable-install dev updates."""

from __future__ import annotations

import fcntl
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir
from sase.core.time import get_timezone
from sase.dev_update.models import (
    DevExecutedCommand,
    DevReconcileStep,
    DevUpdatePlan,
    DevUpdateResult,
)

DEV_UPDATE_JOURNAL: str | None = None
_MAX_STREAM_CHARS = 12_000


def dev_update_journal_path() -> Path:
    """Return the canonical dev-update JSONL path."""
    return Path(DEV_UPDATE_JOURNAL or (sase_subdir("logs") / "dev_update.jsonl"))


def append_dev_update_journal(
    plan: DevUpdatePlan,
    result: DevUpdateResult,
    *,
    restart: Any | None = None,
    path: Path | None = None,
) -> Path | None:
    """Append one best-effort dev-update execution record."""
    target = path or dev_update_journal_path()
    record = _dev_update_journal_record(plan, result, restart=restart)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            try:
                file.write(json.dumps(record, sort_keys=True) + "\n")
            finally:
                fcntl.flock(file, fcntl.LOCK_UN)
    except OSError:
        return None
    return target


def _dev_update_journal_record(
    plan: DevUpdatePlan,
    result: DevUpdateResult,
    *,
    restart: Any | None = None,
) -> dict[str, Any]:
    """Build the serializable journal record for a dev-update run."""
    return {
        "schema_version": 1,
        "timestamp": datetime.now(get_timezone()).isoformat(timespec="seconds"),
        "plan": {
            "packages": [
                {
                    "name": package.record.name,
                    "role": package.record.role,
                    "status": package.status,
                    "reason": package.reason,
                    "git_root": package.git_root,
                    "current_version": package.current_version,
                    "latest_version": package.latest_version,
                    "fetch_error": package.fetch_error,
                }
                for package in plan.packages
            ],
            "roots": [
                {
                    "git_root": root.git_root,
                    "status": root.status,
                    "reason": root.reason,
                    "upstream": root.upstream,
                    "packages": list(root.packages),
                    "fetch_error": root.fetch_error,
                }
                for root in plan.roots
            ],
            "reconcile_steps": [
                _reconcile_step_record(step) for step in plan.reconcile_steps
            ],
        },
        "result": {
            "status": _result_status(result),
            "changed": result.changed,
            "counts": _result_counts(result),
            "outcomes": [
                {
                    "name": outcome.record.name,
                    "role": outcome.record.role,
                    "status": outcome.status,
                    "reason": outcome.reason,
                    "old_version": outcome.old_version,
                    "new_version": outcome.new_version,
                    "git_root": outcome.git_root,
                }
                for outcome in result.outcomes
            ],
        },
        "commands": [_command_record(command) for command in result.commands],
        "restart": _restart_record(restart),
    }


def _restart_record(restart: Any | None) -> dict[str, Any] | None:
    if restart is None:
        return None
    return {
        "attempted": bool(restart.attempted),
        "status": str(restart.status),
        "pid": restart.pid,
        "message": str(restart.message),
        "reason": restart.reason,
        "verified": bool(restart.verified),
        "attempts": [
            {
                "number": attempt.number,
                "status": attempt.status,
                "pid": attempt.pid,
                "message": attempt.message,
                "verified": attempt.verified,
                "verification_error": attempt.verification_error,
            }
            for attempt in restart.attempts
        ],
    }


def _reconcile_step_record(step: DevReconcileStep) -> dict[str, Any]:
    return {
        "kind": step.kind,
        "label": step.label,
        "command": list(step.command),
        "cwd": step.cwd,
        "available": step.available,
        "reason": step.reason,
        "repair_command": list(step.repair_command),
        "repair_cwd": step.repair_cwd,
        "repair_label": step.repair_label,
        "repair_reason": step.repair_reason,
    }


def _command_record(command: DevExecutedCommand) -> dict[str, Any]:
    return {
        "label": command.label,
        "command": list(command.command),
        "cwd": command.cwd,
        "returncode": command.returncode,
        "stdout_tail": _tail(command.stdout),
        "stderr_tail": _tail(command.stderr),
    }


def _tail(text: str) -> str:
    if len(text) <= _MAX_STREAM_CHARS:
        return text
    return text[-_MAX_STREAM_CHARS:]


def _result_status(result: DevUpdateResult) -> str:
    if any(outcome.status == "failed" for outcome in result.outcomes):
        return "failed"
    if any(outcome.status == "updated" for outcome in result.outcomes):
        return "updated"
    return "skipped"


def _result_counts(result: DevUpdateResult) -> dict[str, int]:
    counts = {"updated": 0, "skipped": 0, "failed": 0}
    for outcome in result.outcomes:
        counts[outcome.status] += 1
    return counts
