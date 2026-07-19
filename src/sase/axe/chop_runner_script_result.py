"""Structured-result handling and proposal launch for script-backed chops."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from sase.core.axe_chop_facade import parse_chop_result

from .chop_policy import (
    ChopPreflight,
    apply_chop_once_per,
    release_chop_once_per_keys,
)
from .chop_proposals import (
    launch_chop_proposals,
    prepare_chop_proposals,
    proposal_previews,
)
from .chop_runner_policy import append_once_per_summary
from .chop_runner_script_lifecycle import (
    append_structured_result_summary,
    finalize_script_chop_run,
)
from .chop_runner_trace import NO_PYTHON_TRACEBACK, capture_traceback
from .chop_runner_types import ChopRunOutcome
from .config import ChopConfig
from .state import append_chop_run_output


class _ScriptResult(Protocol):
    returncode: int | None
    output_bytes: int


def _release_unlaunched_once_per_keys(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    accepted_proposals: list[Any],
    successful_launches: list[dict[str, Any]],
) -> None:
    launched_indices = {int(launch["index"]) for launch in successful_launches}
    keys = list(
        dict.fromkeys(
            proposal.dedupe_key
            for proposal in accepted_proposals
            if proposal.index not in launched_indices and proposal.dedupe_key
        )
    )
    if not keys:
        return

    try:
        released = release_chop_once_per_keys(lumberjack_name, chop_name, keys)
    except Exception as exc:
        append_chop_run_output(
            lumberjack_name,
            chop_name,
            run_id,
            f"Failed to release once-per keys after launch failure: {exc}\n",
        )
        return
    append_chop_run_output(
        lumberjack_name,
        chop_name,
        run_id,
        f"Released {released} once-per key(s) after launch failure\n",
    )


def process_script_chop_result(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    run_id: str,
    started_at: datetime,
    result_path: Path,
    result: _ScriptResult,
    dry_run: bool,
    chop_verbose: bool,
    preflight: ChopPreflight,
    launch_agent_from_cwd_fn: Callable[..., Any] | None,
) -> ChopRunOutcome:
    """Validate a script result, apply dedupe, and launch accepted proposals."""
    structured_result: dict[str, Any] | None = None
    proposals: list[dict[str, Any]] = []
    prepared_proposals = []
    if result_path.is_file():
        try:
            structured_result = parse_chop_result(
                result_path.read_text(encoding="utf-8")
            )
            prepared_proposals = prepare_chop_proposals(
                chop.base_name or chop.name,
                structured_result,
                target_key=chop.target_key or None,
                run_id=run_id,
            )
            proposals = proposal_previews(prepared_proposals)
        except Exception as exc:
            tb = capture_traceback()
            finalize_script_chop_run(
                lumberjack_name=lumberjack_name,
                chop_name=chop.name,
                run_id=run_id,
                started_at=started_at,
                status="check_error",
                exit_code=result.returncode,
                error=exc,
                tb=tb,
                result_file=result_path.name,
                dry_run=dry_run,
                preflight=preflight,
            )
            return ChopRunOutcome(
                lumberjack_name=lumberjack_name,
                chop_name=chop.name,
                status="check_error",
                run_id=run_id,
                exit_code=result.returncode,
                output_bytes=result.output_bytes,
                error=exc,
                traceback=tb,
                dry_run=dry_run,
                chop_verbose=chop_verbose,
            )

    if result.returncode != 0:
        error = RuntimeError(f"exit code {result.returncode}")
        finalize_script_chop_run(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="failure",
            exit_code=result.returncode,
            error=error,
            tb=NO_PYTHON_TRACEBACK,
            output_bytes=result.output_bytes,
            result_file=result_path.name if structured_result is not None else None,
            structured_result=structured_result,
            proposals=proposals,
            dry_run=dry_run,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="failure",
            run_id=run_id,
            exit_code=result.returncode,
            output_bytes=result.output_bytes,
            error=error,
            traceback=NO_PYTHON_TRACEBACK,
            result=structured_result,
            proposals=tuple(proposals),
            dry_run=dry_run,
            chop_verbose=chop_verbose,
        )

    if structured_result is None:
        finalize_script_chop_run(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="success",
            exit_code=0,
            output_bytes=result.output_bytes,
            dry_run=dry_run,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="success",
            run_id=run_id,
            exit_code=0,
            output_bytes=result.output_bytes,
            dry_run=dry_run,
            chop_verbose=chop_verbose,
        )

    append_structured_result_summary(
        lumberjack_name,
        chop.name,
        run_id,
        structured_result,
    )
    result_status = str(structured_result["status"])
    if result_status == "check_error":
        error = RuntimeError(
            str(
                structured_result.get("reason")
                or structured_result.get("summary")
                or "chop reported a degraded check"
            )
        )
        finalize_script_chop_run(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="check_error",
            exit_code=0,
            error=error,
            tb=NO_PYTHON_TRACEBACK,
            result_file=result_path.name,
            structured_result=structured_result,
            proposals=proposals,
            dry_run=dry_run,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="check_error",
            run_id=run_id,
            exit_code=0,
            error=error,
            traceback=NO_PYTHON_TRACEBACK,
            result=structured_result,
            proposals=tuple(proposals),
            dry_run=dry_run,
            chop_verbose=chop_verbose,
        )

    if result_status == "no_op":
        finalize_script_chop_run(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="no_op",
            exit_code=0,
            result_file=result_path.name,
            structured_result=structured_result,
            proposals=proposals,
            dry_run=dry_run,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="no_op",
            run_id=run_id,
            exit_code=0,
            result=structured_result,
            proposals=tuple(proposals),
            dry_run=dry_run,
            chop_verbose=chop_verbose,
        )

    try:
        once_per = apply_chop_once_per(
            lumberjack_name=lumberjack_name,
            chop=chop,
            proposals=prepared_proposals,
            persist=not dry_run,
        )
    except Exception as exc:
        tb = capture_traceback()
        finalize_script_chop_run(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="check_error",
            exit_code=0,
            error=exc,
            tb=tb,
            result_file=result_path.name,
            structured_result=structured_result,
            proposals=proposals,
            dry_run=dry_run,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="check_error",
            run_id=run_id,
            exit_code=0,
            error=exc,
            traceback=tb,
            result=structured_result,
            proposals=tuple(proposals),
            dry_run=dry_run,
            chop_verbose=chop_verbose,
        )

    if once_per.decisions:
        proposals = proposal_previews(
            prepared_proposals,
            once_per_decisions=once_per.decisions,
            effective_waits=once_per.effective_waits,
        )
        append_once_per_summary(
            lumberjack_name,
            chop.name,
            run_id,
            once_per.decisions,
        )
    accepted_indices = set(once_per.accepted_indices)
    accepted_proposals = [
        replace(
            proposal,
            dedupe_key=(
                once_per.decisions.get(proposal.index, {}).get("key")
                or proposal.dedupe_key
            ),
            wait_on=once_per.effective_waits[proposal.index],
        )
        for proposal in prepared_proposals
        if proposal.index in accepted_indices
    ]

    if not prepared_proposals or dry_run:
        finalize_script_chop_run(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="success",
            exit_code=0,
            result_file=result_path.name,
            structured_result=structured_result,
            proposals=proposals,
            dry_run=dry_run,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="success",
            run_id=run_id,
            exit_code=0,
            result=structured_result,
            proposals=tuple(proposals),
            dry_run=dry_run,
            chop_verbose=chop_verbose,
        )

    if not accepted_proposals:
        reason = f"all {len(prepared_proposals)} proposal(s) skipped by once-per dedupe"
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
            dry_run=False,
            chop_verbose=chop_verbose,
            reason=reason,
        )

    if launch_agent_from_cwd_fn is None:
        from sase.agent.launcher import launch_agent_from_cwd

        launch_agent_from_cwd_fn = launch_agent_from_cwd
    successful_launches: list[dict[str, Any]] = []
    try:
        launches = launch_chop_proposals(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            proposals=accepted_proposals,
            launch_agent_from_cwd_fn=launch_agent_from_cwd_fn,
            launch_recorded_fn=successful_launches.append,
        )
    except Exception as exc:
        tb = capture_traceback()
        _release_unlaunched_once_per_keys(
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


__all__ = ["process_script_chop_result"]
