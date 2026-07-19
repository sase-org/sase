"""Handler for the top-level ``sase update`` command.

Managed installs still use ``uv tool upgrade sase``. Editable uv-tool installs
route matching editable package records through the dev-update backend: safe git
fast-forwards first, then uv-tool/Rust reconciliation. Every impure dependency
(install probing, runtime inventory, git/subprocess execution, uv, axe restart,
version lookup, and the clock) is injectable so the command remains unit-testable
without a real uv install or daemon.
"""

from __future__ import annotations

import argparse
from inspect import Parameter, signature
import json
import os
import sys
import time
from collections.abc import Callable
from typing import Any

from rich.console import Console

from sase.axe.process import (
    is_axe_running,
    restart_axe_daemon_result,
)
from sase.dev_update import (
    DevUpdatePlan,
    DevUpdateResult,
    execute_dev_update,
    plan_dev_update,
    run_dev_update_command,
)
from sase.dev_update.journal import append_dev_update_journal
from sase.dev_update.models import DevCommandRunner
from sase.config import load_merged_config
from sase.main.update_json import combined_result_json, dry_run_json
from sase.main.update_render import (
    render_dev_update_dry_run,
    render_dev_update_result,
)
from sase.main.update_restart import (
    render_restart_info,
    restart_after_update,
    restart_skipped,
)
from sase.main.update_routing import (
    dev_route,
    installed_version,
    managed_update_argv,
    managed_update_packages,
    managed_summary_receipt,
    should_run_managed_update,
    try_load_receipt,
    update_mode,
)
from sase.main.update_state import combined_changed, dev_update_succeeded
from sase.main.update_types import (
    UPDATE_JSON_SCHEMA_VERSION,
    AxeRunningFn,
    ClockFn,
    ExecuteDevFn,
    InventoryFn,
    PlanDevFn,
    ProbeFn,
    RestartAxeFn,
    RestartInfo,
    RunUvFn,
    VersionFn,
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
from sase.uv_tool.detect import (
    NotUvToolInstall,
    UvToolInstall,
    probe_uv_tool_install,
)
from sase.uv_tool.errors import NotAUvToolInstallError, ReceiptError, UvToolError
from sase.uv_tool.preflight import missing_local_requirements_error
from sase.uv_tool.receipt import ToolReceipt, load_receipt
from sase.uv_tool.render import (
    UpdateSummary,
    render_update_dry_run,
    render_update_result,
    render_uv_tool_error,
    summarize_update,
    summarize_planned_update,
)
from sase.uv_tool.runner import run_uv
from sase.version.inventory import (
    VersionPackageRecord,
    collect_runtime_version_inventory,
)

_installed_version = installed_version


def handle_update_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    probe_fn: ProbeFn = probe_uv_tool_install,
    run_fn: RunUvFn = run_uv,
    inventory_fn: InventoryFn = collect_runtime_version_inventory,
    plan_dev_update_fn: PlanDevFn = plan_dev_update,
    execute_dev_update_fn: ExecuteDevFn = execute_dev_update,
    run_dev_update_fn: DevCommandRunner = run_dev_update_command,
    axe_running_fn: AxeRunningFn = is_axe_running,
    restart_axe_fn: RestartAxeFn = restart_axe_daemon_result,
    version_fn: VersionFn = installed_version,
    clock: ClockFn = time.monotonic,
    config_fn: Callable[[], dict[str, Any]] = load_merged_config,
) -> int:
    """Run ``sase update``; return the process exit code."""
    as_json = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))
    quiet = bool(getattr(args, "quiet", False))
    out = console or Console()
    err = err_console or Console(stderr=True)

    install = probe_fn()
    if isinstance(install, NotUvToolInstall):
        return _fail(NotAUvToolInstallError(install), as_json=as_json, err=err)

    target_mode = getattr(args, "to", None)
    if target_mode is not None:
        return _handle_mode_switch(
            install,
            target_mode=target_mode,
            yes=bool(getattr(args, "yes", False)),
            dry_run=dry_run,
            as_json=as_json,
            quiet=quiet,
            out=out,
            err=err,
            inventory_fn=inventory_fn,
            run_fn=run_fn,
            run_dev_update_fn=run_dev_update_fn,
            axe_running_fn=axe_running_fn,
            restart_axe_fn=restart_axe_fn,
            clock=clock,
            config_fn=config_fn,
        )

    if dry_run:
        return _handle_dry_run(
            install,
            as_json=as_json,
            out=out,
            err=err,
            version_fn=version_fn,
            inventory_fn=inventory_fn,
            plan_dev_update_fn=plan_dev_update_fn,
        )

    return _handle_live_update(
        install,
        as_json=as_json,
        quiet=quiet,
        out=out,
        err=err,
        run_fn=run_fn,
        inventory_fn=inventory_fn,
        plan_dev_update_fn=plan_dev_update_fn,
        execute_dev_update_fn=execute_dev_update_fn,
        run_dev_update_fn=run_dev_update_fn,
        axe_running_fn=axe_running_fn,
        restart_axe_fn=restart_axe_fn,
        version_fn=version_fn,
        clock=clock,
    )


def _handle_mode_switch(
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
        return _fail(exc, as_json=as_json, err=err)

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
        return _fail(
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
        return _fail(exc, as_json=as_json, err=err)
    elapsed = max(0.0, clock() - start)
    restart = restart_after_update(
        changed=result.changed,
        axe_running_fn=axe_running_fn,
        restart_axe_fn=restart_axe_fn,
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


def _handle_live_update(
    install: UvToolInstall,
    *,
    as_json: bool,
    quiet: bool,
    out: Console,
    err: Console,
    run_fn: RunUvFn,
    inventory_fn: InventoryFn,
    plan_dev_update_fn: PlanDevFn,
    execute_dev_update_fn: ExecuteDevFn,
    run_dev_update_fn: DevCommandRunner,
    axe_running_fn: AxeRunningFn,
    restart_axe_fn: RestartAxeFn,
    version_fn: VersionFn,
    clock: ClockFn,
) -> int:
    receipt = try_load_receipt(install)
    route = dev_route(receipt, inventory_fn)
    if isinstance(route, UvToolError):
        return _fail(route, as_json=as_json, err=err)

    has_dev = route is not None and bool(route.records)
    has_managed = should_run_managed_update(receipt, route)
    if has_managed and receipt is not None:
        if (
            error := missing_local_requirements_error(receipt.reconstruct())
        ) is not None:
            return _fail(error, as_json=as_json, err=err)
    mode = update_mode(has_dev=has_dev, has_managed=has_managed)
    argv = managed_update_argv(receipt, route, color="never") if has_managed else []
    managed_packages = (
        managed_update_packages(receipt, route, version_fn=version_fn)
        if has_managed
        else ()
    )

    start = clock()
    dev_plan: DevUpdatePlan | None = None
    dev_result: DevUpdateResult | None = None

    if route is not None and route.records:
        try:
            dev_plan = _call_plan_dev_update(
                plan_dev_update_fn,
                route.records,
                host_record=route.host_record,
                receipt=receipt,
                tool_python=_tool_python(install),
                stale_core_record=route.stale_core_record,
            )
        except Exception as exc:  # noqa: BLE001 - surface planning failures cleanly.
            return _fail(
                UvToolError(f"could not plan editable checkout update: {exc}"),
                as_json=as_json,
                err=err,
            )
        dev_result = execute_dev_update_fn(dev_plan, run=run_dev_update_fn)
        if not dev_update_succeeded(dev_result):
            append_dev_update_journal(
                dev_plan,
                dev_result,
                restart=RestartInfo(
                    attempted=False,
                    status="skipped_no_change",
                    reason="update failed before axe restart",
                ),
            )
            elapsed = max(0.0, clock() - start)
            if as_json:
                print(
                    json.dumps(
                        combined_result_json(
                            mode=mode,
                            managed_argv=argv,
                            managed_summary=None,
                            dev_plan=dev_plan,
                            dev_result=dev_result,
                            elapsed=elapsed,
                            restart=restart_skipped(changed=False),
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                render_dev_update_result(
                    dev_result,
                    elapsed=elapsed,
                    quiet=quiet,
                    console=err,
                    failed=True,
                )
            return 1

    managed_summary: UpdateSummary | None = None
    if has_managed:
        use_spinner = not as_json and not quiet and out.is_terminal
        try:
            if use_spinner:
                with out.status(
                    "Upgrading sase and its plugins via uv…", spinner="dots"
                ):
                    change_set = run_fn(argv)
            else:
                change_set = run_fn(argv)
        except UvToolError as exc:
            if dev_plan is not None and dev_result is not None:
                append_dev_update_journal(
                    dev_plan,
                    dev_result,
                    restart=RestartInfo(
                        attempted=False,
                        status="skipped_no_change",
                        reason="managed update failed before axe restart",
                    ),
                )
            return _fail(exc, as_json=as_json, err=err)
        if route is not None:
            managed_summary = summarize_planned_update(change_set, managed_packages)
        else:
            managed_summary = summarize_update(
                change_set,
                managed_summary_receipt(receipt),
                current_version=version_fn,
            )

    elapsed = max(0.0, clock() - start)
    changed = combined_changed(dev_result, managed_summary)
    restart = restart_after_update(
        changed=changed,
        axe_running_fn=axe_running_fn,
        restart_axe_fn=restart_axe_fn,
    )
    if dev_plan is not None and dev_result is not None:
        append_dev_update_journal(
            dev_plan,
            dev_result,
            restart=restart,
        )

    if as_json:
        print(
            json.dumps(
                combined_result_json(
                    mode=mode,
                    managed_argv=argv,
                    managed_summary=managed_summary,
                    dev_plan=dev_plan,
                    dev_result=dev_result,
                    elapsed=elapsed,
                    restart=restart,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if dev_result is not None:
        render_dev_update_result(
            dev_result, elapsed=elapsed, quiet=quiet, console=out, failed=False
        )
    if managed_summary is not None:
        render_update_result(managed_summary, elapsed=elapsed, quiet=quiet, console=out)
    if changed:
        render_restart_info(restart, console=out, quiet=quiet)
    return 0


def _handle_dry_run(
    install: UvToolInstall,
    *,
    as_json: bool,
    out: Console,
    err: Console,
    version_fn: VersionFn,
    inventory_fn: InventoryFn,
    plan_dev_update_fn: PlanDevFn,
) -> int:
    try:
        receipt = load_receipt(install.receipt_path)
    except ReceiptError as exc:
        return _fail(exc, as_json=as_json, err=err)

    route = dev_route(receipt, inventory_fn)
    if isinstance(route, UvToolError):
        return _fail(route, as_json=as_json, err=err)

    has_dev = route is not None and bool(route.records)
    has_managed = should_run_managed_update(receipt, route)
    if has_managed:
        if (
            error := missing_local_requirements_error(receipt.reconstruct())
        ) is not None:
            return _fail(error, as_json=as_json, err=err)
    mode = update_mode(has_dev=has_dev, has_managed=has_managed)
    argv = managed_update_argv(receipt, route, color="never") if has_managed else []
    packages = (
        managed_update_packages(receipt, route, version_fn=version_fn)
        if has_managed
        else ()
    )

    dev_plan: DevUpdatePlan | None = None
    if route is not None and route.records:
        try:
            dev_plan = _call_plan_dev_update(
                plan_dev_update_fn,
                route.records,
                host_record=route.host_record,
                receipt=receipt,
                tool_python=_tool_python(install),
                stale_core_record=route.stale_core_record,
            )
        except Exception as exc:  # noqa: BLE001 - dry-run should fail legibly.
            return _fail(
                UvToolError(f"could not plan editable checkout update: {exc}"),
                as_json=as_json,
                err=err,
            )

    if as_json:
        print(
            json.dumps(
                dry_run_json(argv, packages, mode=mode, dev_plan=dev_plan),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if dev_plan is None:
        render_update_dry_run(argv, packages, console=out)
    else:
        render_dev_update_dry_run(
            dev_plan, managed_argv=argv, managed_packages=packages, console=out
        )
    return 0


def _fail(error: UvToolError, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_JSON_SCHEMA_VERSION,
                    "error": str(error),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        render_uv_tool_error(str(error), console=err)
    return 1


def _tool_python(install: UvToolInstall) -> str:
    executable = "python.exe" if os.name == "nt" else "python"
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    return str(install.sase_dir / scripts_dir / executable)


def _callable_accepts_keyword(fn: Any, name: str) -> bool:
    try:
        params = signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    for param in params:
        if param.kind is Parameter.VAR_KEYWORD:
            return True
        if param.name == name and param.kind in (
            Parameter.KEYWORD_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False


def _call_plan_dev_update(
    fn: PlanDevFn,
    records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
    *,
    host_record: VersionPackageRecord,
    receipt: ToolReceipt | None,
    tool_python: str,
    stale_core_record: VersionPackageRecord | None = None,
) -> DevUpdatePlan:
    kwargs: dict[str, Any] = {"host_record": host_record, "receipt": receipt}
    if _callable_accepts_keyword(fn, "tool_python"):
        kwargs["tool_python"] = tool_python
    if _callable_accepts_keyword(fn, "stale_core_record"):
        kwargs["stale_core_record"] = stale_core_record
    return fn(records, **kwargs)


__all__ = [
    "UPDATE_JSON_SCHEMA_VERSION",
    "handle_update_command",
]
