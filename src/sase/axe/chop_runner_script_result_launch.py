"""Launch accepted proposals from a script-chop structured result."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .chop_policy import ChopPreflight
from .chop_proposals import launch_chop_proposals, proposal_previews
from .chop_runner_script_lifecycle import finalize_script_chop_run
from .chop_runner_script_result_keys import (
    release_typed_nonlaunched_once_per_keys,
    release_unlaunched_once_per_keys,
)
from .chop_runner_trace import NO_PYTHON_TRACEBACK, capture_traceback
from .chop_runner_types import ChopRunOutcome
from .config import ChopConfig
from .state import append_chop_run_output


def _append_typed_admission_summary(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    admission_result: Any,
) -> None:
    summary = getattr(admission_result, "summary", None)
    if summary is not None:
        append_chop_run_output(
            lumberjack_name,
            chop_name,
            run_id,
            (
                "Typed admission: "
                f"{int(summary.total)} total, "
                f"{int(summary.eligible)} eligible, "
                f"{int(summary.launched)} launched, "
                f"{int(summary.skipped)} skipped, "
                f"{int(summary.condition_errors)} condition error(s), "
                f"{int(summary.launch_errors)} launch error(s)\n"
            ),
        )
    for unit in getattr(admission_result, "unit_results", ()) or ():
        outcome = str(getattr(unit, "outcome", "") or "")
        if outcome == "launched":
            continue
        message = str(getattr(unit, "message", "") or outcome)
        append_chop_run_output(
            lumberjack_name,
            chop_name,
            run_id,
            (
                f"Typed admission unit {getattr(unit, 'logical_id', '')}: "
                f"{outcome}: {message}\n"
            ),
        )


def _typed_admission_failures(admission_result: Any) -> list[str]:
    failures: list[str] = []
    for unit in getattr(admission_result, "unit_results", ()) or ():
        outcome = str(getattr(unit, "outcome", "") or "")
        if outcome not in {"condition_error", "launch_error", "cancelled"}:
            continue
        logical_id = str(getattr(unit, "logical_id", "") or "unknown")
        message = str(getattr(unit, "message", "") or outcome)
        failures.append(f"typed admission {logical_id} {outcome}: {message}")
    return failures


def launch_accepted_script_chop_proposals(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    run_id: str,
    started_at: datetime,
    result_path: Path,
    chop_verbose: bool,
    preflight: ChopPreflight,
    structured_result: dict[str, Any],
    prepared_proposals: list[Any],
    accepted_proposals: list[Any],
    proposals: list[dict[str, Any]],
    once_per_decisions: dict[int, dict[str, str]],
    once_per_effective_waits: dict[int, int | str | None],
    launch_plans: list[Any],
    launch_agent_from_cwd_fn: Callable[..., Any] | None,
    launch_agents_from_cwd_fn: Callable[..., Any] | None,
) -> ChopRunOutcome:
    """Launch accepted proposals and finalize the script-chop run."""
    if launch_agent_from_cwd_fn is None:
        from sase.agent.launcher import launch_agent_from_cwd

        launch_agent_from_cwd_fn = launch_agent_from_cwd
    successful_launches: list[dict[str, Any]] = []
    collision_decisions: dict[int, dict[str, str]] = {}
    collision_effective_waits: dict[int, int | str | None] = {}

    def _record_collision_skip(
        proposal: Any,
        reason: str,
        effective_wait: int | str | None,
    ) -> None:
        collision_decisions[proposal.index] = {
            "outcome": "name_collision",
            "reason": reason,
            "key": proposal.dedupe_key or "",
        }
        collision_effective_waits[proposal.index] = effective_wait
        append_chop_run_output(
            lumberjack_name,
            chop.name,
            run_id,
            (
                f"Skipped proposal {proposal.index + 1} "
                f"({proposal.agent_name}): {reason}\n"
            ),
        )

    def _updated_proposal_previews() -> list[dict[str, Any]]:
        decisions = dict(once_per_decisions)
        decisions.update(collision_decisions)
        effective_waits = dict(once_per_effective_waits)
        effective_waits.update(collision_effective_waits)
        effective_waits.update(
            {
                int(launch["index"]): launch.get("wait_on")
                for launch in successful_launches
            }
        )
        return proposal_previews(
            prepared_proposals,
            once_per_decisions=decisions,
            effective_waits=effective_waits,
            launch_plans=launch_plans,
        )

    try:
        launches = launch_chop_proposals(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            proposals=accepted_proposals,
            launch_agent_from_cwd_fn=launch_agent_from_cwd_fn,
            launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
            launch_plans=launch_plans,
            launch_recorded_fn=successful_launches.append,
            proposal_skipped_fn=_record_collision_skip,
        )
    except Exception as exc:
        tb = capture_traceback()
        proposals = _updated_proposal_previews()
        release_unlaunched_once_per_keys(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            accepted_proposals=accepted_proposals,
            successful_launches=successful_launches,
        )
        partial_launch = bool(successful_launches)
        finalize_script_chop_run(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="launched" if partial_launch else "action_failed",
            exit_code=0,
            agent_pid=(int(successful_launches[0]["pid"]) if partial_launch else None),
            error=exc,
            tb=tb,
            result_file=result_path.name,
            structured_result=structured_result,
            proposals=proposals,
            launches=successful_launches,
            dry_run=False,
            active=partial_launch,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="action_failed",
            run_id=run_id,
            exit_code=0,
            error=exc,
            traceback=tb,
            result=structured_result,
            proposals=tuple(proposals),
            launches=tuple(successful_launches),
            dry_run=False,
            chop_verbose=chop_verbose,
        )

    proposals = _updated_proposal_previews()
    typed_admission = getattr(launches, "typed_admission", None)
    admission_result = getattr(launches, "admission_result", None)
    if typed_admission is not None and admission_result is not None:
        _append_typed_admission_summary(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            admission_result=admission_result,
        )
        admission_failures = _typed_admission_failures(admission_result)
        admission_complete = bool(getattr(admission_result, "admission_complete", True))
        if not admission_complete:
            first_pid = int(launches[0]["pid"]) if launches else None
            finalize_script_chop_run(
                lumberjack_name=lumberjack_name,
                chop_name=chop.name,
                run_id=run_id,
                started_at=started_at,
                status="launched",
                exit_code=0,
                agent_pid=first_pid,
                result_file=result_path.name,
                structured_result=structured_result,
                proposals=proposals,
                launches=successful_launches,
                dry_run=False,
                active=True,
                typed_admission=typed_admission,
                preflight=preflight,
            )
            return ChopRunOutcome(
                lumberjack_name=lumberjack_name,
                chop_name=chop.name,
                status="launched",
                run_id=run_id,
                exit_code=0,
                agent_pid=first_pid,
                result=structured_result,
                proposals=tuple(proposals),
                launches=tuple(successful_launches),
                dry_run=False,
                chop_verbose=chop_verbose,
            )

        if not launches:
            status: Literal["action_failed", "action_succeeded"] = (
                "action_failed" if admission_failures else "action_succeeded"
            )
            detail = (
                "; ".join(admission_failures)
                if admission_failures
                else "typed admission completed with no agent launches"
            )
            release_typed_nonlaunched_once_per_keys(
                lumberjack_name=lumberjack_name,
                chop_name=chop.name,
                run_id=run_id,
                typed_admission=typed_admission,
                admission_result=admission_result,
                after="typed admission",
            )
            finalize_script_chop_run(
                lumberjack_name=lumberjack_name,
                chop_name=chop.name,
                run_id=run_id,
                started_at=started_at,
                status=status,
                exit_code=0,
                error=RuntimeError(detail) if admission_failures else None,
                tb=NO_PYTHON_TRACEBACK if admission_failures else None,
                result_file=result_path.name,
                structured_result=structured_result,
                proposals=proposals,
                launches=[],
                dry_run=False,
                reason=None if admission_failures else detail,
                typed_admission=typed_admission,
                preflight=preflight,
                checkpoint_event=status,
            )
            return ChopRunOutcome(
                lumberjack_name=lumberjack_name,
                chop_name=chop.name,
                status=status,
                run_id=run_id,
                exit_code=0,
                error=RuntimeError(detail) if admission_failures else None,
                traceback=NO_PYTHON_TRACEBACK if admission_failures else None,
                result=structured_result,
                proposals=tuple(proposals),
                launches=(),
                dry_run=False,
                chop_verbose=chop_verbose,
                reason=None if admission_failures else detail,
            )

        for launch in launches:
            append_chop_run_output(
                lumberjack_name,
                chop.name,
                run_id,
                (
                    f"Launched proposal {int(launch['index']) + 1} as "
                    f"{launch['agent_name']} (PID {launch['pid']})\n"
                ),
            )
        first_pid = int(launches[0]["pid"])
        failure_detail = "; ".join(admission_failures)
        finalize_script_chop_run(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="launched",
            exit_code=0,
            agent_pid=first_pid,
            error=RuntimeError(failure_detail) if admission_failures else None,
            tb=NO_PYTHON_TRACEBACK if admission_failures else None,
            result_file=result_path.name,
            structured_result=structured_result,
            proposals=proposals,
            launches=successful_launches,
            dry_run=False,
            active=True,
            typed_admission=typed_admission,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="launched",
            run_id=run_id,
            exit_code=0,
            agent_pid=first_pid,
            error=RuntimeError(failure_detail) if admission_failures else None,
            traceback=NO_PYTHON_TRACEBACK if admission_failures else None,
            result=structured_result,
            proposals=tuple(proposals),
            launches=tuple(successful_launches),
            dry_run=False,
            chop_verbose=chop_verbose,
        )

    if collision_decisions:
        release_unlaunched_once_per_keys(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            accepted_proposals=accepted_proposals,
            successful_launches=successful_launches,
            after="agent-name collision skip",
        )

    if not launches:
        duplicate_count = sum(
            decision.get("outcome") == "duplicate"
            for decision in once_per_decisions.values()
        )
        collision_count = len(collision_decisions)
        if duplicate_count:
            reason = (
                f"all {len(prepared_proposals)} proposal(s) skipped "
                f"({duplicate_count} by once-per dedupe, "
                f"{collision_count} by agent-name collision)"
            )
        else:
            reason = (
                f"all {len(prepared_proposals)} proposal(s) skipped by "
                "agent-name collision"
            )
        finalize_script_chop_run(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="skipped",
            exit_code=0,
            result_file=result_path.name,
            structured_result=structured_result,
            proposals=proposals,
            launches=[],
            dry_run=False,
            reason=reason,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="skipped",
            run_id=run_id,
            exit_code=0,
            result=structured_result,
            proposals=tuple(proposals),
            launches=(),
            dry_run=False,
            chop_verbose=chop_verbose,
            reason=reason,
        )

    for launch in launches:
        append_chop_run_output(
            lumberjack_name,
            chop.name,
            run_id,
            (
                f"Launched proposal {int(launch['index']) + 1} as "
                f"{launch['agent_name']} (PID {launch['pid']})\n"
            ),
        )
    first_pid = int(launches[0]["pid"])
    finalize_script_chop_run(
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        run_id=run_id,
        started_at=started_at,
        status="launched",
        exit_code=0,
        agent_pid=first_pid,
        result_file=result_path.name,
        structured_result=structured_result,
        proposals=proposals,
        launches=launches,
        dry_run=False,
        active=True,
        preflight=preflight,
    )
    return ChopRunOutcome(
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        status="launched",
        run_id=run_id,
        exit_code=0,
        agent_pid=first_pid,
        result=structured_result,
        proposals=tuple(proposals),
        launches=tuple(launches),
        dry_run=False,
        chop_verbose=chop_verbose,
    )


__all__ = ["launch_accepted_script_chop_proposals"]
