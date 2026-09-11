"""Live (non-dry-run, non-mode-switch) execution path for ``sase update``."""

from __future__ import annotations

import json
from collections.abc import Callable

from rich.console import Console

from sase.dev_update import DevUpdatePlan, DevUpdateResult
from sase.dev_update.journal import append_dev_update_journal
from sase.dev_update.models import DevCommandRunner
from sase.completion.install import CompletionRefreshReport
from sase.main.update_handler_completion import (
    _completion_refresh_after_update,
    _render_completion_refresh,
)
from sase.main.update_handler_support import (
    _call_plan_dev_update,
    _fail,
    _tool_python,
)
from sase.main.update_json import combined_result_json
from sase.main.update_render import render_dev_update_result
from sase.main.update_restart import (
    render_restart_info,
    restart_after_update,
    restart_skipped,
)
from sase.main.update_routing import (
    dev_route,
    managed_summary_receipt,
    managed_update_argv,
    managed_update_packages,
    should_run_managed_update,
    try_load_receipt,
    update_mode,
)
from sase.main.update_state import combined_changed, dev_update_succeeded
from sase.main.update_types import (
    AxeRunningFn,
    ClockFn,
    ExecuteDevFn,
    InventoryFn,
    PlanDevFn,
    RestartAxeFn,
    RestartInfo,
    RunUvFn,
    VersionFn,
)
from sase.uv_tool.detect import UvToolInstall
from sase.uv_tool.errors import UvToolError
from sase.uv_tool.preflight import missing_local_requirements_error
from sase.uv_tool.render import (
    UpdateSummary,
    render_update_result,
    summarize_planned_update,
    summarize_update,
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
    refresh_completions_fn: Callable[[], CompletionRefreshReport] | None = None,
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
        source="sase update",
    )
    if dev_plan is not None and dev_result is not None:
        append_dev_update_journal(
            dev_plan,
            dev_result,
            restart=restart,
        )

    refresh = _completion_refresh_after_update(install, refresh_completions_fn)

    if as_json:
        payload = combined_result_json(
            mode=mode,
            managed_argv=argv,
            managed_summary=managed_summary,
            dev_plan=dev_plan,
            dev_result=dev_result,
            elapsed=elapsed,
            restart=restart,
        )
        if refresh.attempted:
            payload["completion_refresh"] = refresh.to_json()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if dev_result is not None:
        render_dev_update_result(
            dev_result, elapsed=elapsed, quiet=quiet, console=out, failed=False
        )
    if managed_summary is not None:
        render_update_result(managed_summary, elapsed=elapsed, quiet=quiet, console=out)
    if changed:
        render_restart_info(restart, console=out, quiet=quiet)
    _render_completion_refresh(refresh, console=out, quiet=quiet)
    return 0
