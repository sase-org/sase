"""``sase update --to <mode>`` handling: plan, confirm, and execute a mode switch."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from rich.console import Console

# Self-update safety: a mode switch reinstalls the very code the running
# process imports, so every module the rest of the run needs is imported
# here at module top level, never lazily after execution starts.
from sase.completion.install import CompletionRefreshReport
from sase.dev_update.models import DevCommandRunner
from sase.main.update_handler_completion import (
    completion_refresh_after_update,
    render_completion_refresh,
)
from sase.main.update_handler_support import (
    COMPLETIONS_STEP_ID,
    COMPLETIONS_STEP_TITLE,
    RESTART_STEP_ID,
    RESTART_STEP_TITLE,
    ProgressSessionFactory,
    fail_update,
    finish_completions_step,
    finish_restart_step,
    print_interrupted,
    session_log_path,
)
from sase.main.update_restart import render_restart_info, restart_after_update
from sase.main.update_types import (
    ClockFn,
    InventoryFn,
    RestartSchedulerFn,
    RunUvFn,
    SchedulerRunningFn,
)
from sase.mode_switch import (
    execute_mode_switch,
    mode_switch_dry_run_json,
    mode_switch_result_json,
    plan_mode_switch,
    render_mode_switch_noop,
    render_mode_switch_plan,
    render_mode_switch_result,
)
from sase.mode_switch.models import SwitchPlan, TargetMode
from sase.update_progress import StepSpec
from sase.update_progress.session import UpdateProgressSession
from sase.uv_tool.detect import UvToolInstall
from sase.uv_tool.errors import UvToolError


def _default_progress_session(
    *,
    err: Console,
    as_json: bool,
    quiet: bool,
    verbose: bool,
) -> UpdateProgressSession:
    """Build a real progress session on the default clock and log directory."""
    return UpdateProgressSession(
        err, argv=sys.argv, as_json=as_json, quiet=quiet, verbose=verbose
    )


def handle_mode_switch(
    install: UvToolInstall,
    *,
    target_mode: TargetMode,
    yes: bool,
    dry_run: bool,
    as_json: bool,
    quiet: bool,
    out: Console,
    err: Console,
    inventory_fn: InventoryFn,
    run_fn: RunUvFn,
    run_dev_update_fn: DevCommandRunner,
    scheduler_running_fn: SchedulerRunningFn,
    restart_scheduler_fn: RestartSchedulerFn,
    clock: ClockFn,
    config_fn: Callable[[], dict[str, Any]],
    refresh_completions_fn: Callable[[], CompletionRefreshReport] | None = None,
    verbose: bool = False,
    progress_session_factory: ProgressSessionFactory | None = None,
) -> int:
    try:
        plan = plan_mode_switch(
            install,
            target_mode=target_mode,
            config=config_fn(),
            inventory_fn=inventory_fn,
        )
    except UvToolError as exc:
        return fail_update(exc, as_json=as_json, err=err)

    if not plan.changed:
        if dry_run:
            if as_json:
                payload = mode_switch_dry_run_json(plan)
                payload["dry_run"] = True
                payload["changed"] = False
                payload["log_path"] = None
                print(json.dumps(payload, indent=2, sort_keys=True))
            elif not quiet:
                render_mode_switch_noop(plan, console=out)
            return 0
        refresh = completion_refresh_after_update(install, refresh_completions_fn)
        if as_json:
            payload = mode_switch_dry_run_json(plan)
            payload["dry_run"] = False
            payload["changed"] = False
            payload["log_path"] = None
            if refresh.attempted:
                payload["completion_refresh"] = refresh.to_json()
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            if not quiet:
                render_mode_switch_noop(plan, console=out)
            render_completion_refresh(refresh, console=out, quiet=quiet)
        return 0

    if dry_run:
        if as_json:
            print(json.dumps(mode_switch_dry_run_json(plan), indent=2, sort_keys=True))
        else:
            render_mode_switch_plan(plan, console=out)
        return 0

    # The confirmation prompt and plan preview stay before any live region
    # starts. Never prompt inside Live.
    if not yes:
        try:
            confirmed = _confirm_mode_switch(plan, out=out, err=err)
        except KeyboardInterrupt:
            err.print("Interrupted", style="yellow")
            return 130
        if not confirmed:
            return fail_update(
                UvToolError("mode switch cancelled. Re-run with --yes."),
                as_json=as_json,
                err=err,
            )

    factory = progress_session_factory or _default_progress_session
    session = factory(err=err, as_json=as_json, quiet=quiet, verbose=verbose)
    session.set_header(f"switch to {target_mode}")
    with session:
        try:
            return _run_mode_switch(
                install,
                session,
                plan,
                as_json=as_json,
                quiet=quiet,
                out=out,
                err=err,
                run_fn=run_fn,
                run_dev_update_fn=run_dev_update_fn,
                scheduler_running_fn=scheduler_running_fn,
                restart_scheduler_fn=restart_scheduler_fn,
                clock=clock,
                refresh_completions_fn=refresh_completions_fn,
            )
        except KeyboardInterrupt:
            session.interrupt()
            session.print_final()
            print_interrupted(err, session_log_path(session))
            return 130


def _run_mode_switch(
    install: UvToolInstall,
    session: UpdateProgressSession,
    plan: SwitchPlan,
    *,
    as_json: bool,
    quiet: bool,
    out: Console,
    err: Console,
    run_fn: RunUvFn,
    run_dev_update_fn: DevCommandRunner,
    scheduler_running_fn: SchedulerRunningFn,
    restart_scheduler_fn: RestartSchedulerFn,
    clock: ClockFn,
    refresh_completions_fn: Callable[[], CompletionRefreshReport] | None,
) -> int:
    """Execute a confirmed switch inside the session; return the exit code."""
    progress = session.progress
    # Trailing rows render below the switch steps and show as pending while
    # the switch runs.
    progress.declare(
        (
            StepSpec(RESTART_STEP_ID, RESTART_STEP_TITLE, trailing=True),
            StepSpec(COMPLETIONS_STEP_ID, COMPLETIONS_STEP_TITLE, trailing=True),
        )
    )
    start = clock()
    try:
        result = execute_mode_switch(
            plan,
            run_uv_fn=run_fn,
            run_command_fn=run_dev_update_fn,
            progress=progress,
        )
    except UvToolError as exc:
        # The backend already finished the failing step as failed; the
        # restore hint stays in the error panel below the final frame.
        session.print_final()
        return fail_update(
            exc, as_json=as_json, err=err, log_path=session_log_path(session)
        )
    elapsed = max(0.0, clock() - start)
    progress.start(RESTART_STEP_ID, title=RESTART_STEP_TITLE)
    restart = restart_after_update(
        changed=result.changed,
        scheduler_running_fn=scheduler_running_fn,
        restart_scheduler_fn=restart_scheduler_fn,
        source="sase update mode switch",
    )
    finish_restart_step(progress, restart)
    progress.start(COMPLETIONS_STEP_ID, title=COMPLETIONS_STEP_TITLE)
    refresh = completion_refresh_after_update(install, refresh_completions_fn)
    finish_completions_step(progress, refresh)

    log_path = session_log_path(session)
    session.print_final()

    if as_json:
        payload = mode_switch_result_json(
            result, elapsed=elapsed, restart=restart, log_path=log_path
        )
        if refresh.attempted:
            payload["completion_refresh"] = refresh.to_json()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    render_mode_switch_result(result, elapsed=elapsed, quiet=quiet, console=out)
    if result.changed:
        render_restart_info(restart, console=out, quiet=quiet)
    render_completion_refresh(refresh, console=out, quiet=quiet)
    return 0


def _confirm_mode_switch(plan: SwitchPlan, *, out: Console, err: Console) -> bool:
    if not sys.stdin.isatty():
        render_mode_switch_plan(plan, console=err)
        err.print("Re-run with --yes.", style="yellow")
        return False
    render_mode_switch_plan(plan, console=out)
    try:
        answer = out.input("Proceed? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}
