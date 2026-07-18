"""Script-chop execution and live-run dedupe for the shared chop runner."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.hooks.processes import is_process_running
from sase.core.axe_chop_facade import parse_chop_result
from sase.core.time import get_timezone

from .chop_agents import build_chop_launch_env
from .chop_lifecycle import finalize_launched_chop_runs
from .chop_policy import (
    ChopCheckpointEvent,
    ChopPreflight,
    apply_chop_once_per,
    evaluate_chop_preflight,
    record_chop_checkpoint_event,
)
from .chop_runner_policy import (
    append_once_per_summary,
    record_checkpoint_best_effort,
    record_preflight_outcome,
)
from .chop_proposals import (
    launch_chop_proposals,
    prepare_chop_proposals,
    proposal_previews,
)
from .chop_script_runner import discover_chop_script, stream_chop_script
from .config import AxeConfig, ChopConfig
from .state import (
    ChopRunEntry,
    ChopRunSource,
    ChopRunStatus,
    append_chop_run_output,
    chop_run_context_path,
    chop_run_log_path,
    chop_run_result_path,
    ensure_lumberjack_dirs,
    finish_chop_run,
    generate_chop_run_id,
    read_chop_run,
    read_chop_run_index,
    start_chop_run,
    update_chop_run_pid,
    write_chop_run,
)
from .chop_runner_context import build_oneshot_context
from .chop_script_context import prepare_chop_run_context
from .chop_runner_trace import NO_PYTHON_TRACEBACK, capture_traceback
from .chop_runner_types import ChopRunOutcome


PIDLESS_SCRIPT_CHOP_STALE_FALLBACK_SECONDS = 300


def _pidless_script_chop_stale_after_seconds(resolved_timeout: int | None) -> int:
    """Return the grace window before PID-less running script rows are stale."""
    if resolved_timeout is not None and resolved_timeout > 0:
        return resolved_timeout
    return PIDLESS_SCRIPT_CHOP_STALE_FALLBACK_SECONDS


def _script_chop_run_age_seconds(entry: ChopRunEntry, now: datetime) -> float | None:
    """Return run age in seconds, or None when ``started_at`` is unreadable."""
    try:
        started_at = datetime.fromisoformat(entry.started_at)
    except ValueError:
        return None
    if started_at.tzinfo is None:
        if now.tzinfo is not None:
            now = datetime.now()
    elif now.tzinfo is None:
        now = now.replace(tzinfo=started_at.tzinfo)
    else:
        now = now.astimezone(started_at.tzinfo)
    return max(0.0, (now - started_at).total_seconds())


def active_script_chop_run(
    lumberjack_name: str,
    chop_name: str,
    *,
    pidless_stale_after_seconds: int | None = None,
    is_process_running_fn: Callable[[int], bool] = is_process_running,
) -> ChopRunEntry | None:
    """Return the newest chop run entry if its script or action is active.

    Only the head of the index is inspected: pruning keeps active runs at the
    front, and a finalized newest entry means there is no live run to dedupe
    against. A ``running`` row with a stored PID is trusted only while that
    process is still alive; dead-PID rows are finalized so the next scheduled
    run can recover. PID-less rows are kept active only for a grace window so
    a crash before PID recording cannot block future runs indefinitely.
    """
    index = read_chop_run_index(lumberjack_name, chop_name)
    if not index:
        return None
    head_id = index[0]
    head = read_chop_run(lumberjack_name, chop_name, head_id)
    if head is None:
        return None
    if head.status == "launched":
        return head
    if head.status != "running":
        return None

    if head.pid is not None and head.pid > 0:
        if not is_process_running_fn(head.pid):
            _finalize_stale_script_chop_run(
                head,
                reason=f"stale running chop process exited: pid {head.pid}",
            )
            return None
        return head

    stale_after = _pidless_script_chop_stale_after_seconds(pidless_stale_after_seconds)
    age_seconds = _script_chop_run_age_seconds(head, datetime.now(get_timezone()))
    if age_seconds is None or age_seconds >= stale_after:
        _finalize_stale_script_chop_run(
            head,
            reason=(
                "stale running chop never recorded a pid after "
                f"{stale_after}s grace window"
            ),
        )
        return None

    return head


def _finalize_stale_script_chop_run(entry: ChopRunEntry, *, reason: str) -> None:
    """Mark a running script-chop entry stale after dedupe proves it stale."""
    finished_at = datetime.now(get_timezone())
    try:
        started_at = datetime.fromisoformat(entry.started_at)
    except ValueError:
        duration_ms = 0
    else:
        if started_at.tzinfo is None:
            finished_at_for_duration = datetime.now()
        else:
            finished_at_for_duration = finished_at.astimezone(started_at.tzinfo)
        duration_ms = max(
            0,
            int((finished_at_for_duration - started_at).total_seconds() * 1000),
        )

    try:
        finish_chop_run(
            entry.lumberjack_name,
            entry.chop_name,
            entry.run_id,
            status="failure",
            finished_at=finished_at.isoformat(),
            duration_ms=duration_ms,
            exit_code=None,
            error=reason,
            traceback=NO_PYTHON_TRACEBACK,
        )
    except OSError:
        pass


def run_script_chop_once(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    axe_config: AxeConfig,
    chop_timeout_default: int | None,
    context_file: str | None,
    source: ChopRunSource,
    started_by: str | None,
    dry_run: bool = False,
    chop_verbose: bool = False,
    force: bool = False,
    discover_chop_script_fn: Callable[
        [str, list[str]], Path | None
    ] = discover_chop_script,
    stream_chop_script_fn: Callable[..., Any] = stream_chop_script,
    build_context_fn: Callable[[str, AxeConfig], str] = build_oneshot_context,
    is_process_running_fn: Callable[[int], bool] = is_process_running,
    launch_agent_from_cwd_fn: Callable[..., Any] | None = None,
) -> ChopRunOutcome:
    resolved_timeout = chop.timeout or chop_timeout_default
    finalize_launched_chop_runs(lumberjack_name, [chop.name])
    live = active_script_chop_run(
        lumberjack_name,
        chop.name,
        pidless_stale_after_seconds=resolved_timeout,
        is_process_running_fn=is_process_running_fn,
    )
    if live is not None:
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="already_running",
            run_id=live.run_id,
        )

    started_at = datetime.now(get_timezone())
    run_id = generate_chop_run_id(started_at)

    state_dir = ensure_lumberjack_dirs(lumberjack_name)
    if context_file is None:
        try:
            context_file = build_context_fn(lumberjack_name, axe_config)
        except Exception as exc:
            preflight = ChopPreflight(
                outcome="check_error",
                reason=f"could not build chop policy context: {exc}",
            )
            return record_preflight_outcome(
                lumberjack_name=lumberjack_name,
                chop_name=chop.name,
                run_id=run_id,
                started_at=started_at,
                source=source,
                started_by=started_by,
                preflight=preflight,
                chop_verbose=chop_verbose,
            )

    preflight = evaluate_chop_preflight(
        lumberjack_name=lumberjack_name,
        chop=chop,
        context_file=context_file,
        scheduled=source == "scheduled",
        force=force,
        now=started_at,
    )
    if preflight.outcome != "fire":
        return record_preflight_outcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            source=source,
            started_by=started_by,
            preflight=preflight,
            chop_verbose=chop_verbose,
        )
    try:
        record_chop_checkpoint_event(
            lumberjack_name,
            chop.name,
            preflight,
            "observed",
            now=started_at,
        )
    except Exception as exc:
        return record_preflight_outcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            source=source,
            started_by=started_by,
            preflight=ChopPreflight(
                outcome="check_error",
                reason=f"could not persist chop checkpoint observation: {exc}",
            ),
            chop_verbose=chop_verbose,
        )

    script_name = chop.script_name
    script = discover_chop_script_fn(script_name, axe_config.chop_script_dirs)
    if script is None:
        error = RuntimeError(
            f"Chop script not found: {script_name} (chop: {chop.name})"
        )
        finished_at = datetime.now(get_timezone())
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        try:
            write_chop_run(
                ChopRunEntry(
                    run_id=run_id,
                    lumberjack_name=lumberjack_name,
                    chop_name=chop.name,
                    started_at=started_at.isoformat(),
                    finished_at=finished_at.isoformat(),
                    duration_ms=duration_ms,
                    status="missing_script",
                    error=str(error),
                    traceback=NO_PYTHON_TRACEBACK,
                    source=source,
                    started_by=started_by,
                )
            )
        except OSError:
            pass
        record_checkpoint_best_effort(
            lumberjack_name,
            chop.name,
            preflight,
            "action_failed",
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="missing_script",
            run_id=run_id,
            error=error,
            traceback=NO_PYTHON_TRACEBACK,
        )

    env = dict(chop.env)
    env.update(
        build_chop_launch_env(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            prompt=None,
            run_id=run_id,
        )
    )
    if chop_verbose or axe_config.verbose_lumberjack_diagnostics:
        env["SASE_CHOP_VERBOSE"] = "1"

    start_entry = ChopRunEntry(
        run_id=run_id,
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        started_at=started_at.isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
        source=source,
        started_by=started_by,
    )
    try:
        start_chop_run(start_entry)
    except OSError:
        pass
    try:
        record_chop_checkpoint_event(
            lumberjack_name,
            chop.name,
            preflight,
            "action_accepted",
        )
    except Exception as exc:
        tb = capture_traceback()
        _finalize(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="check_error",
            error=exc,
            tb=tb,
            preflight=preflight,
            checkpoint_event="action_failed",
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="check_error",
            run_id=run_id,
            error=exc,
            traceback=tb,
            dry_run=dry_run,
            chop_verbose=chop_verbose,
        )

    log_path = chop_run_log_path(lumberjack_name, chop.name, run_id)
    result_path = chop_run_result_path(lumberjack_name, chop.name, run_id)
    run_context_path = chop_run_context_path(lumberjack_name, chop.name, run_id)
    env["SASE_CHOP_RESULT_FILE"] = str(result_path)
    try:
        context_file = prepare_chop_run_context(
            context_file,
            result_file=str(result_path),
            destination=str(run_context_path),
        )
    except Exception as e:
        tb = capture_traceback()
        _finalize(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="check_error",
            error=e,
            tb=tb,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="check_error",
            run_id=run_id,
            error=e,
            traceback=tb,
            dry_run=dry_run,
            chop_verbose=chop_verbose,
        )

    def _record_pid(pid: int) -> None:
        try:
            update_chop_run_pid(lumberjack_name, chop.name, run_id, pid)
        except OSError:
            pass

    try:
        result = stream_chop_script_fn(
            script,
            context_file,
            log_path=log_path,
            timeout=resolved_timeout,
            env=env,
            cwd=str(state_dir),
            on_pid=_record_pid,
        )
    except Exception as e:
        tb = capture_traceback()
        _finalize(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="failure",
            exit_code=None,
            error=e,
            tb=tb,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="failure",
            run_id=run_id,
            error=e,
            traceback=tb,
        )

    if result.timed_out:
        error = RuntimeError(f"timed out after {resolved_timeout}s")
        _finalize(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="timeout",
            exit_code=None,
            error=error,
            tb=NO_PYTHON_TRACEBACK,
            output_bytes=result.output_bytes,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="timeout",
            run_id=run_id,
            output_bytes=result.output_bytes,
            error=error,
            traceback=NO_PYTHON_TRACEBACK,
            dry_run=dry_run,
            chop_verbose=chop_verbose,
        )

    structured_result: dict[str, Any] | None = None
    proposals: list[dict[str, Any]] = []
    prepared_proposals = []
    if result_path.is_file():
        try:
            structured_result = parse_chop_result(
                result_path.read_text(encoding="utf-8")
            )
            prepared_proposals = prepare_chop_proposals(
                chop.name,
                structured_result,
            )
            proposals = proposal_previews(prepared_proposals)
        except Exception as e:
            tb = capture_traceback()
            _finalize(
                lumberjack_name=lumberjack_name,
                chop_name=chop.name,
                run_id=run_id,
                started_at=started_at,
                status="check_error",
                exit_code=result.returncode,
                error=e,
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
                error=e,
                traceback=tb,
                dry_run=dry_run,
                chop_verbose=chop_verbose,
            )

    if result.returncode != 0:
        error = RuntimeError(f"exit code {result.returncode}")
        _finalize(
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
        _finalize(
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

    _append_structured_result_summary(
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
        _finalize(
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
        _finalize(
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
    except Exception as e:
        tb = capture_traceback()
        _finalize(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="check_error",
            exit_code=0,
            error=e,
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
            error=e,
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
        )
        append_once_per_summary(
            lumberjack_name,
            chop.name,
            run_id,
            once_per.decisions,
        )
    accepted_indices = set(once_per.accepted_indices)
    accepted_proposals = [
        proposal
        for proposal in prepared_proposals
        if proposal.index in accepted_indices
    ]

    if not prepared_proposals or dry_run:
        _finalize(
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
        _finalize(
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
    try:
        launches = launch_chop_proposals(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            proposals=accepted_proposals,
            launch_agent_from_cwd_fn=launch_agent_from_cwd_fn,
        )
    except Exception as e:
        tb = capture_traceback()
        _finalize(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="action_failed",
            exit_code=0,
            error=e,
            tb=tb,
            result_file=result_path.name,
            structured_result=structured_result,
            proposals=proposals,
            dry_run=False,
            preflight=preflight,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="action_failed",
            run_id=run_id,
            exit_code=0,
            error=e,
            traceback=tb,
            result=structured_result,
            proposals=tuple(proposals),
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
    _finalize(
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


def _append_structured_result_summary(
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


def _finalize(
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


_active_script_chop_run = active_script_chop_run
_run_script_chop_once = run_script_chop_once
