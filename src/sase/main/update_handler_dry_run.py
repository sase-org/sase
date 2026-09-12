"""``sase update --dry-run`` handling."""

from __future__ import annotations

import json

from rich.console import Console

from sase.dev_update import DevUpdatePlan
from sase.main.update_handler_support import (
    call_plan_dev_update,
    fail_update,
    tool_python,
)
from sase.main.update_json import dry_run_json
from sase.main.update_render import render_dev_update_dry_run
from sase.main.update_routing import (
    dev_route,
    managed_update_argv,
    managed_update_packages,
    should_run_managed_update,
    update_mode,
)
from sase.main.update_types import InventoryFn, PlanDevFn, VersionFn
from sase.uv_tool.detect import UvToolInstall
from sase.uv_tool.errors import ReceiptError, UvToolError
from sase.uv_tool.preflight import missing_local_requirements_error
from sase.uv_tool.receipt import load_receipt
from sase.uv_tool.render import render_update_dry_run


def handle_dry_run(
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
        return fail_update(exc, as_json=as_json, err=err)

    route = dev_route(receipt, inventory_fn)
    if isinstance(route, UvToolError):
        return fail_update(route, as_json=as_json, err=err)

    has_dev = route is not None and bool(route.records)
    has_managed = should_run_managed_update(receipt, route)
    if has_managed:
        if (
            error := missing_local_requirements_error(receipt.reconstruct())
        ) is not None:
            return fail_update(error, as_json=as_json, err=err)
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
            dev_plan = call_plan_dev_update(
                plan_dev_update_fn,
                route.records,
                host_record=route.host_record,
                receipt=receipt,
                tool_python=tool_python(install),
                stale_core_record=route.stale_core_record,
            )
        except Exception as exc:  # noqa: BLE001 - dry-run should fail legibly.
            return fail_update(
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
