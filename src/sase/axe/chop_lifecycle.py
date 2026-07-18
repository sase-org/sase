"""Finalize runner-owned chop actions from linked agent artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from sase.ace.hooks.processes import is_process_running
from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
from sase.core.time import get_timezone

from .chop_agents import (
    get_chop_agent_records,
    remove_chop_agent_records,
)
from .chop_policy import finalize_pending_chop_checkpoints
from .state import (
    ChopRunEntry,
    ChopRunStatus,
    append_chop_run_output,
    finish_chop_run,
    read_chop_run,
    read_chop_run_index,
)

_SUCCESS_DONE_OUTCOMES = {
    "completed",
    "epic_approved",
    "noop",
    "plan_committed",
    "plan_rejected",
}


@dataclass(frozen=True)
class _AgentCompletion:
    terminal: bool
    succeeded: bool
    detail: str


def _record_artifacts_dir(record: object) -> Path | None:
    project_name = str(getattr(record, "project_name", ""))
    timestamp = str(getattr(record, "artifacts_timestamp", ""))
    if not project_name or not timestamp:
        return None
    return resolve_agent_artifact_timestamp_path(
        project_name,
        "ace-run",
        timestamp,
    )


def _agent_completion(record: object) -> _AgentCompletion:
    pid = int(getattr(record, "pid", 0) or 0)
    artifacts_dir = _record_artifacts_dir(record)
    done_path = artifacts_dir / "done.json" if artifacts_dir is not None else None
    if done_path is not None and done_path.is_file():
        try:
            raw = json.loads(done_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _AgentCompletion(
                terminal=True,
                succeeded=False,
                detail=f"agent pid {pid} has unreadable done.json: {exc}",
            )
        if not isinstance(raw, dict):
            return _AgentCompletion(
                terminal=True,
                succeeded=False,
                detail=f"agent pid {pid} done.json is not an object",
            )
        outcome = str(raw.get("outcome") or "")
        if outcome in _SUCCESS_DONE_OUTCOMES or (
            outcome == "failed" and raw.get("retried_as_timestamp")
        ):
            return _AgentCompletion(
                terminal=True,
                succeeded=True,
                detail=f"agent pid {pid} finished with outcome {outcome}",
            )
        return _AgentCompletion(
            terminal=True,
            succeeded=False,
            detail=f"agent pid {pid} finished with outcome {outcome or 'unknown'}",
        )

    if pid > 0 and is_process_running(pid):
        return _AgentCompletion(
            terminal=False,
            succeeded=False,
            detail=f"agent pid {pid} is still running",
        )
    location = str(done_path) if done_path is not None else "an unknown artifact path"
    return _AgentCompletion(
        terminal=True,
        succeeded=False,
        detail=f"agent pid {pid} exited without completion artifact {location}",
    )


def _duration_ms(entry: ChopRunEntry, finished_at: datetime) -> int:
    try:
        started_at = datetime.fromisoformat(entry.started_at)
    except ValueError:
        return entry.duration_ms
    if started_at.tzinfo is None:
        finished = finished_at.replace(tzinfo=None)
    else:
        finished = finished_at.astimezone(started_at.tzinfo)
    return max(0, int((finished - started_at).total_seconds() * 1000))


def finalize_launched_chop_runs(
    lumberjack_name: str,
    chop_names: list[str] | tuple[str, ...],
) -> int:
    """Finalize launched runs whose linked agents are all terminal.

    Returns the number of run-history entries transitioned during this pass.
    Missing linkage and dead agents without completion artifacts fail closed so
    a run cannot remain in ``launched`` forever.
    """
    finalized = 0
    for chop_name in chop_names:
        for run_id in read_chop_run_index(lumberjack_name, chop_name):
            entry = read_chop_run(lumberjack_name, chop_name, run_id)
            if entry is None or entry.status != "launched":
                continue

            records = get_chop_agent_records(
                lumberjack_name,
                chop_name=chop_name,
                run_id=run_id,
            )
            expected = len(entry.launches)
            if expected == 0 or len(records) < expected:
                detail = (
                    f"launch registry linkage incomplete: expected {expected} "
                    f"agent record(s), found {len(records)}"
                )
                completions = [_AgentCompletion(True, False, detail)]
            else:
                completions = [_agent_completion(record) for record in records]

            if any(not completion.terminal for completion in completions):
                continue

            failures = [
                completion.detail
                for completion in completions
                if not completion.succeeded
            ]
            checkpoint_event: Literal["action_succeeded", "action_failed"] = (
                "action_failed" if failures else "action_succeeded"
            )
            try:
                finalize_pending_chop_checkpoints(
                    lumberjack_name,
                    chop_name,
                    checkpoint_event,
                )
            except Exception as exc:
                failures.append(f"checkpoint finalization failed: {exc}")
            status: ChopRunStatus = "action_failed" if failures else "action_succeeded"
            detail = (
                "; ".join(failures)
                if failures
                else (
                    f"all {len(completions)} launched agent(s) completed successfully"
                )
            )
            append_chop_run_output(
                lumberjack_name,
                chop_name,
                run_id,
                f"\nChop action lifecycle: {status}: {detail}\n",
            )
            finished_at = datetime.now(get_timezone())
            finish_chop_run(
                lumberjack_name,
                chop_name,
                run_id,
                status=status,
                finished_at=finished_at.isoformat(),
                duration_ms=_duration_ms(entry, finished_at),
                exit_code=entry.exit_code,
                agent_pid=entry.agent_pid,
                error=detail if failures else None,
                traceback=None,
            )
            remove_chop_agent_records(
                lumberjack_name,
                chop_name=chop_name,
                run_id=run_id,
            )
            finalized += 1
    return finalized


__all__ = ["finalize_launched_chop_runs"]
