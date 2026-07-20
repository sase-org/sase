"""CLI rendering for ``sase plugin update <plugin>`` / ``--all``.

Like :mod:`sase.plugins.cli_install`, this delegates all *resolution* and
*orchestration* to the console-free :mod:`sase.plugins.operations` layer and
keeps only presentation: a spinner, the Rich result panels, the stable
``-j|--json`` payloads, and the exit codes. The operations layer detects a
managed ``uv tool install sase`` (*D4*), reads sase's uv receipt as the source
of truth for the injected set (*D2*), and upgrades the requested plugin(s) with
``uv tool install <full set> --upgrade-package <name>`` — upgrading only the
named plugins while leaving sase core and every other plugin pinned (decision
*D3*'s complement: "update plugins" never silently bumps core). ``-a|--all``
upgrades every injected plugin in one shot; ``-n|--dry-run`` previews the uv
argv; ``-j|--json`` emits a stable payload.

The common case resolves the plugin straight from the receipt, so no catalog
fetch happens unless the plugin is missing — only then is the catalog consulted
to tell "known but not installed" apart from "unknown name".
"""

from __future__ import annotations

import argparse
import importlib.metadata as importlib_metadata
import json
import time
from collections.abc import Callable
from typing import Any

from rich.console import Console

from sase.axe.process import is_axe_running, restart_axe_daemon_result
from sase.main.update_json import restart_info_json
from sase.main.update_restart import render_restart_info
from sase.main.update_types import AxeRunningFn, RestartAxeFn, RestartInfo
from sase.plugins.catalog import PluginCatalogError, load_plugin_catalog
from sase.plugins.cli_restart import restart_after_plugin_change
from sase.plugins.operations import (
    ClockFn,
    LoadFn,
    NoPlugins,
    NotInstalled,
    NotUvTool,
    ProbeFn,
    RunUvFn,
    UpdateOutcome,
    UpdateReady,
    UpdateUnknown,
    execute_update,
    plan_update,
)
from sase.plugins.render import (
    render_no_plugins_installed,
    render_plugin_not_installed,
    render_plugin_update_dry_run,
    render_plugin_update_result,
    render_show_not_found,
)
from sase.uv_tool.detect import probe_uv_tool_install
from sase.uv_tool.errors import ReceiptError, UvToolError
from sase.uv_tool.render import render_uv_tool_error
from sase.uv_tool.runner import ChangeKind, run_uv

#: Bump when the ``-j|--json`` payload shape changes incompatibly.
UPDATE_PLUGIN_JSON_SCHEMA_VERSION = 1

VersionFn = Callable[[str], str | None]


def _installed_version(name: str) -> str | None:
    """Return the installed version of distribution *name*, or ``None``."""
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 — version display must never crash the run.
        return None


def handle_plugin_update_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    load_fn: LoadFn = load_plugin_catalog,
    probe_fn: ProbeFn = probe_uv_tool_install,
    run_fn: RunUvFn = run_uv,
    version_fn: VersionFn = _installed_version,
    axe_running_fn: AxeRunningFn = is_axe_running,
    restart_axe_fn: RestartAxeFn = restart_axe_daemon_result,
    clock: ClockFn = time.monotonic,
) -> int:
    """Run ``sase plugin update``; return the process exit code."""
    query = getattr(args, "plugin", None)
    all_plugins = bool(getattr(args, "all", False))
    refresh = bool(getattr(args, "refresh", False))
    dry_run = bool(getattr(args, "dry_run", False))
    as_json = bool(getattr(args, "json", False))
    out = console or Console()
    err = err_console or Console(stderr=True)

    if not all_plugins and not query:
        return _usage_error(as_json=as_json, err=err)

    try:
        plan = plan_update(
            query,
            all_plugins=all_plugins,
            refresh=refresh,
            load_fn=load_fn,
            probe_fn=probe_fn,
        )
    except PluginCatalogError as exc:
        return _fail_catalog(exc, as_json=as_json, err=err)
    except ReceiptError as exc:
        return _fail(exc, as_json=as_json, err=err)

    if isinstance(plan, NotUvTool):
        return _fail(plan.error, as_json=as_json, err=err)
    if isinstance(plan, NoPlugins):
        return _no_plugins(as_json=as_json, out=out)
    if isinstance(plan, UpdateUnknown):
        return _not_found(plan, as_json=as_json, err=err)
    if isinstance(plan, NotInstalled):
        return _not_installed(plan.name, as_json=as_json, err=err)

    if dry_run:
        return _dry_run(plan, as_json=as_json, out=out)

    use_spinner = not as_json and out.is_terminal
    try:
        if use_spinner:
            with out.status("Upgrading plugins via uv…", spinner="dots"):
                outcome = execute_update(plan, run_fn=run_fn, clock=clock)
        else:
            outcome = execute_update(plan, run_fn=run_fn, clock=clock)
    except UvToolError as exc:
        return _fail(exc, as_json=as_json, err=err)

    restart = restart_after_plugin_change(
        outcome.change_set,
        axe_running_fn=axe_running_fn,
        restart_axe_fn=restart_axe_fn,
        source="sase plugin update",
    )

    if as_json:
        print(
            json.dumps(
                _result_json(outcome, version_fn, restart),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    render_plugin_update_result(
        change_set=outcome.change_set,
        dist_names=outcome.plan.targets,
        all_plugins=outcome.plan.all_plugins,
        elapsed=outcome.elapsed,
        current_version=version_fn,
        console=out,
    )
    render_restart_info(restart, console=out, quiet=False)
    return 0


# --------------------------------------------------------------------------- #
# Rendering / JSON helpers
# --------------------------------------------------------------------------- #


def _dry_run(plan: UpdateReady, *, as_json: bool, out: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_PLUGIN_JSON_SCHEMA_VERSION,
                    "dry_run": True,
                    "all": plan.all_plugins,
                    "command": list(plan.argv),
                    "plugins": list(plan.targets),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    render_plugin_update_dry_run(
        argv=plan.argv,
        dist_names=plan.targets,
        all_plugins=plan.all_plugins,
        console=out,
    )
    return 0


def _no_plugins(*, as_json: bool, out: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_PLUGIN_JSON_SCHEMA_VERSION,
                    "all": True,
                    "plugins": [],
                    "changed": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    render_no_plugins_installed(console=out)
    return 0


def _not_installed(name: str, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_PLUGIN_JSON_SCHEMA_VERSION,
                    "installed": False,
                    "plugin": name,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    render_plugin_not_installed(short_name=name, console=err)
    return 1


def _not_found(plan: UpdateUnknown, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_PLUGIN_JSON_SCHEMA_VERSION,
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


def _usage_error(*, as_json: bool, err: Console) -> int:
    message = "Specify a plugin to update, or pass -a|--all to update them all."
    if as_json:
        print(
            json.dumps(
                {"schema_version": UPDATE_PLUGIN_JSON_SCHEMA_VERSION, "error": message},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        err.print(message)
    return 2


def _fail(error: UvToolError, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_PLUGIN_JSON_SCHEMA_VERSION,
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
                    "schema_version": UPDATE_PLUGIN_JSON_SCHEMA_VERSION,
                    "error": str(error),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        err.print(str(error))
    return 1


def _result_json(
    outcome: UpdateOutcome, version_fn: VersionFn, restart: RestartInfo
) -> dict[str, Any]:
    change_set = outcome.change_set
    plugins = []
    for name in outcome.plan.targets:
        change = change_set.get(name)
        if change is None:
            plugins.append(
                {
                    "name": name,
                    "kind": ChangeKind.UNCHANGED.value,
                    "old_version": version_fn(name),
                    "new_version": version_fn(name),
                }
            )
        else:
            plugins.append(
                {
                    "name": change.name,
                    "kind": change.kind.value,
                    "old_version": change.old_version,
                    "new_version": change.new_version,
                }
            )
    upgraded = sum(1 for p in plugins if p["kind"] == ChangeKind.UPGRADED.value)
    return {
        "schema_version": UPDATE_PLUGIN_JSON_SCHEMA_VERSION,
        "dry_run": False,
        "command": list(outcome.plan.argv),
        "changed": upgraded > 0,
        "elapsed_seconds": round(outcome.elapsed, 3),
        "counts": {"updated": upgraded, "already_current": len(plugins) - upgraded},
        "plugins": plugins,
        "restart": restart_info_json(restart),
    }


__all__ = [
    "UPDATE_PLUGIN_JSON_SCHEMA_VERSION",
    "handle_plugin_update_command",
]
