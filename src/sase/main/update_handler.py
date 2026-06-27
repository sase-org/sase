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
import json
import time

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
from sase.dev_update.models import DevCommandRunner
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
    managed_summary_receipt,
    planned_packages,
    planned_packages_for_requirements,
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
    RunUvFn,
    VersionFn,
)
from sase.uv_tool.commands import build_upgrade_all
from sase.uv_tool.detect import (
    NotUvToolInstall,
    UvToolInstall,
    probe_uv_tool_install,
)
from sase.uv_tool.errors import NotAUvToolInstallError, ReceiptError, UvToolError
from sase.uv_tool.receipt import load_receipt
from sase.uv_tool.render import (
    UpdateSummary,
    render_update_dry_run,
    render_update_result,
    render_uv_tool_error,
    summarize_update,
)
from sase.uv_tool.runner import run_uv
from sase.version.inventory import collect_runtime_version_inventory

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
    mode = update_mode(has_dev=has_dev, has_managed=has_managed)
    argv = build_upgrade_all(color="never") if has_managed else []

    start = clock()
    dev_plan: DevUpdatePlan | None = None
    dev_result: DevUpdateResult | None = None

    if route is not None and route.records:
        try:
            dev_plan = plan_dev_update_fn(
                route.records, host_record=route.host_record, receipt=receipt
            )
        except Exception as exc:  # noqa: BLE001 - surface planning failures cleanly.
            return _fail(
                UvToolError(f"could not plan editable checkout update: {exc}"),
                as_json=as_json,
                err=err,
            )
        dev_result = execute_dev_update_fn(dev_plan, run=run_dev_update_fn)
        if not dev_update_succeeded(dev_result):
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
            return _fail(exc, as_json=as_json, err=err)
        managed_summary = summarize_update(
            change_set, managed_summary_receipt(receipt), current_version=version_fn
        )

    elapsed = max(0.0, clock() - start)
    changed = combined_changed(dev_result, managed_summary)
    restart = restart_after_update(
        changed=changed,
        axe_running_fn=axe_running_fn,
        restart_axe_fn=restart_axe_fn,
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
    mode = update_mode(has_dev=has_dev, has_managed=has_managed)
    argv = build_upgrade_all(color="never") if has_managed else []
    packages = (
        planned_packages(receipt, version_fn)
        if mode == "managed"
        else planned_packages_for_requirements(
            route.managed_requirements if route is not None else (),
            receipt=receipt,
            version_fn=version_fn,
        )
    )

    dev_plan: DevUpdatePlan | None = None
    if route is not None and route.records:
        try:
            dev_plan = plan_dev_update_fn(
                route.records, host_record=route.host_record, receipt=receipt
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


__all__ = [
    "UPDATE_JSON_SCHEMA_VERSION",
    "handle_update_command",
]
