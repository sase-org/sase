"""Run-history finalization helpers for script-backed chops."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.core.time import get_timezone

from .chop_policy import ChopCheckpointEvent, ChopPreflight
from .chop_runner_policy import record_checkpoint_best_effort
from .state import (
    ChopRunStatus,
    append_chop_run_output,
    finish_chop_run,
)


def append_structured_result_summary(
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    result: dict[str, Any],
) -> None:
    parts = [f"Structured chop result: {result['status']}"]
    if result.get("summary"):
        parts.append(str(result["summary"]))
    if result.get("reason"):
        parts.append(f"reason={result['reason']}")
    proposed = result.get("proposed_launches", [])
    parts.append(f"proposals={len(proposed) if isinstance(proposed, list) else 0}")
    append_chop_run_output(
        lumberjack_name,
        chop_name,
        run_id,
        "\n" + " · ".join(parts) + "\n",
    )


def finalize_script_chop_run(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    started_at: datetime,
    status: ChopRunStatus,
    exit_code: int | None = None,
    agent_pid: int | None = None,
    error: Exception | None = None,
    tb: str | None = None,
    output_bytes: int | None = None,
    result_file: str | None = None,
    structured_result: dict[str, Any] | None = None,
    proposals: list[dict[str, Any]] | None = None,
    launches: list[dict[str, Any]] | None = None,
    dry_run: bool | None = None,
    active: bool = False,
    reason: str | None = None,
    preflight: ChopPreflight | None = None,
    checkpoint_event: ChopCheckpointEvent | None = None,
) -> None:
    """Stamp a lifecycle transition onto a streaming run entry."""
    finished_at = datetime.now(get_timezone())
    duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    try:
        finish_chop_run(
            lumberjack_name,
            chop_name,
            run_id,
            status=status,
            finished_at=None if active else finished_at.isoformat(),
            duration_ms=duration_ms,
            exit_code=exit_code,
            agent_pid=agent_pid,
            error=str(error) if error is not None else None,
            traceback=tb,
            output_bytes=output_bytes,
            result_file=result_file,
            result=structured_result,
            proposals=proposals,
            launches=launches,
            dry_run=dry_run,
            reason=reason,
        )
    except OSError:
        pass
    if preflight is None:
        return
    if checkpoint_event is None:
        if status in {"success", "no_op", "skipped"}:
            checkpoint_event = "action_succeeded"
        elif status in {
            "failure",
            "timeout",
            "missing_script",
            "check_error",
            "action_failed",
        }:
            checkpoint_event = "action_failed"
    if checkpoint_event is not None:
        record_checkpoint_best_effort(
            lumberjack_name,
            chop_name,
            preflight,
            checkpoint_event,
            run_id=run_id,
        )


__all__ = ["append_structured_result_summary", "finalize_script_chop_run"]
