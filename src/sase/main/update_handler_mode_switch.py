"""``sase update --to <mode>`` handling: plan, confirm, and execute a mode switch."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from rich.console import Console

from sase.dev_update.models import DevCommandRunner
from sase.main.update_handler_support import fail_update
from sase.main.update_restart import render_restart_info, restart_after_update
from sase.main.update_types import (
    AxeRunningFn,
    ClockFn,
    InventoryFn,
    RestartAxeFn,
    RunUvFn,
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
from sase.uv_tool.detect import UvToolInstall
from sase.uv_tool.errors import UvToolError


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
    axe_running_fn: AxeRunningFn,
    restart_axe_fn: RestartAxeFn,
    clock: ClockFn,
    config_fn: Callable[[], dict[str, Any]],
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
        if as_json:
            payload = mode_switch_dry_run_json(plan)
            payload["dry_run"] = dry_run
            payload["changed"] = False
            print(json.dumps(payload, indent=2, sort_keys=True))
        elif not quiet:
            render_mode_switch_noop(plan, console=out)
        return 0

    if dry_run:
        if as_json:
            print(json.dumps(mode_switch_dry_run_json(plan), indent=2, sort_keys=True))
        else:
            render_mode_switch_plan(plan, console=out)
        return 0

    if not yes and not _confirm_mode_switch(plan, out=out, err=err):
        return fail_update(
            UvToolError("mode switch cancelled. Re-run with --yes."),
            as_json=as_json,
            err=err,
        )

    start = clock()
    try:
        result = execute_mode_switch(
            plan,
            run_uv_fn=run_fn,
            run_command_fn=run_dev_update_fn,
        )
    except UvToolError as exc:
        return fail_update(exc, as_json=as_json, err=err)
    elapsed = max(0.0, clock() - start)
    restart = restart_after_update(
        changed=result.changed,
        axe_running_fn=axe_running_fn,
        restart_axe_fn=restart_axe_fn,
        source="sase update mode switch",
    )

    if as_json:
        print(
            json.dumps(
                mode_switch_result_json(result, elapsed=elapsed, restart=restart),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    render_mode_switch_result(result, elapsed=elapsed, quiet=quiet, console=out)
    if result.changed:
        render_restart_info(restart, console=out, quiet=quiet)
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
