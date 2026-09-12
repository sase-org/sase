"""Handler for the top-level ``sase update`` command.

Managed installs still use ``uv tool upgrade sase``. Editable uv-tool installs
route matching editable package records through the dev-update backend: safe git
fast-forwards first, then uv-tool/Rust reconciliation. Every impure dependency
(install probing, runtime inventory, git/subprocess execution, uv, axe restart,
version lookup, and the clock) is injectable so the command remains unit-testable
without a real uv install or daemon.

The mode-switch, dry-run, and live-update paths are dispatched to sibling
``update_handler_*`` modules; this module only wires argument defaults and
routes to the right one.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from typing import Any

from rich.console import Console

from sase.axe.process import (
    is_axe_running,
    restart_axe_daemon_result,
)
from sase.dev_update import execute_dev_update, plan_dev_update
from sase.dev_update.models import DevCommandRunner
from sase.config import load_merged_config
from sase.completion.install import CompletionRefreshReport
from sase.dev_update import run_dev_update_command
from sase.main.update_handler_dry_run import handle_dry_run
from sase.main.update_handler_live import handle_live_update
from sase.main.update_handler_mode_switch import handle_mode_switch
from sase.main.update_handler_support import fail_update
from sase.main.update_routing import installed_version
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
from sase.uv_tool.detect import NotUvToolInstall, probe_uv_tool_install
from sase.uv_tool.errors import NotAUvToolInstallError
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
    config_fn: Callable[[], dict[str, Any]] = load_merged_config,
    refresh_completions_fn: Callable[[], CompletionRefreshReport] | None = None,
) -> int:
    """Run ``sase update``; return the process exit code."""
    as_json = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))
    quiet = bool(getattr(args, "quiet", False))
    out = console or Console()
    err = err_console or Console(stderr=True)

    install = probe_fn()
    if isinstance(install, NotUvToolInstall):
        return fail_update(NotAUvToolInstallError(install), as_json=as_json, err=err)

    target_mode = getattr(args, "to", None)
    if target_mode is not None:
        return handle_mode_switch(
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
        return handle_dry_run(
            install,
            as_json=as_json,
            out=out,
            err=err,
            version_fn=version_fn,
            inventory_fn=inventory_fn,
            plan_dev_update_fn=plan_dev_update_fn,
        )

    return handle_live_update(
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
        refresh_completions_fn=refresh_completions_fn,
    )


__all__ = [
    "UPDATE_JSON_SCHEMA_VERSION",
    "handle_update_command",
]
