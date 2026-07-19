"""Script-chop orchestration and compatibility surface for the shared runner."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.hooks.processes import is_process_running
from sase.core.time import get_timezone

from .chop_agents import build_chop_launch_env
from .chop_env import chop_target_env, resolve_chop_env
from .chop_lifecycle import finalize_launched_chop_runs
from .chop_policy import (
    ChopPreflight,
    evaluate_chop_preflight,
    record_chop_checkpoint_event,
)
from .chop_runner_policy import (
    record_checkpoint_best_effort,
    record_preflight_outcome,
)
from .chop_runner_context import build_oneshot_context
from .chop_runner_script_dedupe import (
    PIDLESS_SCRIPT_CHOP_STALE_FALLBACK_SECONDS,
    active_script_chop_run,
)
from .chop_runner_script_lifecycle import (
    append_structured_result_summary as _append_structured_result_summary,
    finalize_script_chop_run as _finalize,
)
from .chop_runner_script_result import process_script_chop_result
from .chop_runner_trace import NO_PYTHON_TRACEBACK, capture_traceback
from .chop_runner_types import ChopRunOutcome
from .chop_script_runner import discover_chop_script, stream_chop_script
from .chop_script_context import prepare_chop_run_context
from .config import AxeConfig, ChopConfig
from .state import (
    ChopRunEntry,
    ChopRunSource,
    chop_run_context_path,
    chop_run_log_path,
    chop_run_result_path,
    ensure_lumberjack_dirs,
    generate_chop_run_id,
    start_chop_run,
    update_chop_run_pid,
    write_chop_run,
)


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

    try:
        env = resolve_chop_env(chop.env)
        env.update(chop_target_env(chop.target_key, chop.target))
    except Exception as exc:
        outcome = record_preflight_outcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            source=source,
            started_by=started_by,
            preflight=ChopPreflight(
                outcome="check_error",
                reason=f"could not resolve chop environment: {exc}",
            ),
            chop_verbose=chop_verbose,
        )
        record_checkpoint_best_effort(
            lumberjack_name,
            chop.name,
            preflight,
            "action_failed",
            run_id=run_id,
        )
        return outcome
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
            target=chop.target,
            vars=chop.vars,
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

    return process_script_chop_result(
        lumberjack_name=lumberjack_name,
        chop=chop,
        run_id=run_id,
        started_at=started_at,
        result_path=result_path,
        result=result,
        dry_run=dry_run,
        chop_verbose=chop_verbose,
        preflight=preflight,
        launch_agent_from_cwd_fn=launch_agent_from_cwd_fn,
    )


_active_script_chop_run = active_script_chop_run
_run_script_chop_once = run_script_chop_once
