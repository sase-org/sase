"""Finalize runner-owned chop actions from linked agent artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sase.core.time import get_timezone

from ._chop_lifecycle_completion import agent_completion
from ._chop_lifecycle_keys import (
    log_unmatched_records,
    release_failed_launch_keys,
    release_typed_nonlaunched_keys,
)
from ._chop_lifecycle_matching import duration_ms, match_records_to_launches
from ._chop_lifecycle_types import AgentCompletion
from ._chop_lifecycle_typed_admission import typed_admission_reconciliation
from .chop_agents import (
    garbage_collect_chop_agent_records,
    get_chop_agent_records,
    remove_chop_agent_records,
)
from .chop_policy import finalize_pending_chop_checkpoints
from .state import (
    ChopRunStatus,
    append_chop_run_output,
    finish_chop_run,
    read_chop_run,
    read_chop_run_index,
)


def finalize_launched_chop_runs(
    lumberjack_name: str,
    chop_names: list[str] | tuple[str, ...],
) -> int:
    """Finalize launched runs whose linked agents are all terminal.

    Returns the number of run-history entries transitioned during this pass.
    Missing linkage and dead agents without completion artifacts fail closed so
    a run cannot remain in ``launched`` forever.
    """
    garbage_collect_chop_agent_records(lumberjack_name)
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
            typed_reconciliation = typed_admission_reconciliation(
                entry=entry,
                records=list(records),
            )
            if typed_reconciliation.waiting:
                continue
            if typed_reconciliation.applies:
                release_typed_nonlaunched_keys(
                    lumberjack_name=lumberjack_name,
                    chop_name=chop_name,
                    run_id=run_id,
                    keys=list(typed_reconciliation.release_keys or []),
                )
            launches = (
                list(typed_reconciliation.launches or [])
                if typed_reconciliation.applies
                else list(entry.launches)
            )
            matched_records, unmatched_records, linkage_failures = (
                match_records_to_launches(list(records), launches)
            )
            if linkage_failures:
                completions = [
                    AgentCompletion(True, False, detail) for detail in linkage_failures
                ]
            else:
                completions = [
                    agent_completion(matched.record) for matched in matched_records
                ]

            if any(not completion.terminal for completion in completions):
                continue

            log_unmatched_records(
                lumberjack_name=lumberjack_name,
                chop_name=chop_name,
                run_id=run_id,
                records=unmatched_records,
            )

            if matched_records and not linkage_failures:
                release_failed_launch_keys(
                    lumberjack_name=lumberjack_name,
                    chop_name=chop_name,
                    run_id=run_id,
                    matched_records=matched_records,
                    completions=completions,
                )

            failures = list(typed_reconciliation.failures or [])
            if entry.error and not typed_reconciliation.applies:
                failures.append(f"proposal launch failed: {entry.error}")
            failures.extend(
                completion.detail
                for completion in completions
                if not completion.succeeded
            )
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
                    typed_reconciliation.success_detail
                    if typed_reconciliation.applies
                    else f"all {len(launches)} launched agent(s) completed successfully"
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
                duration_ms=duration_ms(entry, finished_at),
                exit_code=entry.exit_code,
                agent_pid=entry.agent_pid,
                error=detail if failures else None,
                traceback=entry.traceback,
            )
            remove_chop_agent_records(
                lumberjack_name,
                chop_name=chop_name,
                run_id=run_id,
            )
            finalized += 1
    return finalized


__all__ = ["finalize_launched_chop_runs"]
