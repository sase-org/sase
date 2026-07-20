"""CLI rendering for ``sase plugin uninstall <plugin>``.

The inverse of :mod:`sase.plugins.cli_install`: it delegates all *resolution* and
*orchestration* to the console-free :mod:`sase.plugins.operations` layer and keeps
only presentation — a spinner, the Rich result panels, the stable ``-j|--json``
payloads, and the exit codes. The operations layer detects a managed
``uv tool install sase`` (*D4*), reads sase's uv receipt as the source of truth
for the injected set (*D2*), and rebuilds the install with the target plugin
omitted (``uv tool install <primary> --with <remaining...>``) — preserving sase
core and every other plugin (decision *D3*'s spirit: removing one plugin never
touches the rest).

The common case resolves the plugin straight from the receipt, so no catalog
fetch happens unless the plugin is missing — only then is the catalog consulted
to tell a known-but-already-absent plugin (a no-op success, since uninstall is
idempotent) apart from an unknown name. ``-n|--dry-run`` previews the exact uv
argv; ``-j|--json`` emits a stable payload.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from rich.console import Console

from sase.axe.process import is_axe_running, restart_axe_daemon_result
from sase.main.update_json import restart_info_json
from sase.main.update_restart import render_restart_info
from sase.main.update_types import AxeRunningFn, RestartAxeFn, RestartInfo
from sase.plugins.catalog import PluginCatalogError, load_plugin_catalog
from sase.plugins.cli_restart import restart_after_plugin_change
from sase.plugins.operations import (
    AlreadyAbsent,
    ClockFn,
    LoadFn,
    NotUvTool,
    ProbeFn,
    RunUvFn,
    UninstallOutcome,
    UninstallReady,
    UninstallUnknown,
    execute_uninstall,
    plan_uninstall,
)
from sase.plugins.render import (
    render_plugin_uninstall_dry_run,
    render_plugin_uninstall_not_installed,
    render_plugin_uninstall_result,
    render_show_not_found,
)
from sase.uv_tool.detect import probe_uv_tool_install
from sase.uv_tool.errors import ReceiptError, UvToolError
from sase.uv_tool.render import render_uv_tool_error
from sase.uv_tool.runner import ChangeKind, run_uv

#: Bump when the ``-j|--json`` payload shape changes incompatibly.
UNINSTALL_PLUGIN_JSON_SCHEMA_VERSION = 1


def handle_plugin_uninstall_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    load_fn: LoadFn = load_plugin_catalog,
    probe_fn: ProbeFn = probe_uv_tool_install,
    run_fn: RunUvFn = run_uv,
    axe_running_fn: AxeRunningFn = is_axe_running,
    restart_axe_fn: RestartAxeFn = restart_axe_daemon_result,
    clock: ClockFn = time.monotonic,
) -> int:
    """Run ``sase plugin uninstall <plugin>``; return the process exit code."""
    query = str(getattr(args, "plugin", "") or "")
    refresh = bool(getattr(args, "refresh", False))
    dry_run = bool(getattr(args, "dry_run", False))
    as_json = bool(getattr(args, "json", False))
    out = console or Console()
    err = err_console or Console(stderr=True)

    try:
        plan = plan_uninstall(
            query, refresh=refresh, load_fn=load_fn, probe_fn=probe_fn
        )
    except PluginCatalogError as exc:
        return _fail_catalog(exc, as_json=as_json, err=err)
    except ReceiptError as exc:
        return _fail(exc, as_json=as_json, err=err)

    if isinstance(plan, NotUvTool):
        return _fail(plan.error, as_json=as_json, err=err)
    if isinstance(plan, UninstallUnknown):
        return _not_found(plan, as_json=as_json, err=err)
    if isinstance(plan, AlreadyAbsent):
        return _already_absent(plan.name, as_json=as_json, out=out)

    if dry_run:
        return _dry_run(plan, as_json=as_json, out=out)

    use_spinner = not as_json and out.is_terminal
    try:
        if use_spinner:
            with out.status(
                f"Uninstalling {plan.display_name} via uv…", spinner="dots"
            ):
                outcome = execute_uninstall(plan, run_fn=run_fn, clock=clock)
        else:
            outcome = execute_uninstall(plan, run_fn=run_fn, clock=clock)
    except UvToolError as exc:
        return _fail(exc, as_json=as_json, err=err)

    restart = restart_after_plugin_change(
        outcome.change_set,
        axe_running_fn=axe_running_fn,
        restart_axe_fn=restart_axe_fn,
        source="sase plugin uninstall",
    )

    if as_json:
        print(json.dumps(_result_json(outcome, restart), indent=2, sort_keys=True))
        return 0

    render_plugin_uninstall_result(
        change_set=outcome.change_set,
        dist_name=outcome.plan.dist_name,
        short_name=outcome.plan.display_name,
        elapsed=outcome.elapsed,
        console=out,
    )
    render_restart_info(restart, console=out, quiet=False)
    return 0


# --------------------------------------------------------------------------- #
# Rendering / JSON helpers
# --------------------------------------------------------------------------- #


def _dry_run(plan: UninstallReady, *, as_json: bool, out: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UNINSTALL_PLUGIN_JSON_SCHEMA_VERSION,
                    "dry_run": True,
                    "command": list(plan.argv),
                    "plugin": plan.display_name,
                    "distribution": plan.dist_name,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    render_plugin_uninstall_dry_run(
        argv=plan.argv, short_name=plan.display_name, console=out
    )
    return 0


def _already_absent(name: str, *, as_json: bool, out: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UNINSTALL_PLUGIN_JSON_SCHEMA_VERSION,
                    "dry_run": False,
                    "installed": False,
                    "changed": False,
                    "plugin": name,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    render_plugin_uninstall_not_installed(short_name=name, console=out)
    return 0


def _not_found(plan: UninstallUnknown, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UNINSTALL_PLUGIN_JSON_SCHEMA_VERSION,
                    "found": False,
                    "query": plan.query,
                    "suggestions": [entry.name for entry in plan.suggestions],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    render_show_not_found(plan.query, plan.suggestions, console=err)
    return 1


def _fail(error: UvToolError, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UNINSTALL_PLUGIN_JSON_SCHEMA_VERSION,
                    "error": str(error),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        render_uv_tool_error(str(error), console=err)
    return 1


def _fail_catalog(error: PluginCatalogError, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UNINSTALL_PLUGIN_JSON_SCHEMA_VERSION,
                    "error": str(error),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        err.print(str(error))
    return 1


def _result_json(outcome: UninstallOutcome, restart: RestartInfo) -> dict[str, Any]:
    plan = outcome.plan
    change = outcome.change_set.get(plan.dist_name)
    removed = change is not None and change.kind is ChangeKind.REMOVED
    return {
        "schema_version": UNINSTALL_PLUGIN_JSON_SCHEMA_VERSION,
        "dry_run": False,
        "command": list(plan.argv),
        "plugin": plan.display_name,
        "distribution": plan.dist_name,
        "changed": removed,
        "removed_version": change.old_version if change is not None else None,
        "elapsed_seconds": round(outcome.elapsed, 3),
        "restart": restart_info_json(restart),
    }


__all__ = [
    "UNINSTALL_PLUGIN_JSON_SCHEMA_VERSION",
    "handle_plugin_uninstall_command",
]
