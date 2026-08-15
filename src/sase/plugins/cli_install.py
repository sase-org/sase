"""CLI rendering for ``sase plugin install <plugin>``.

This is the PatchI-facing seam that delegates all *resolution* and *orchestration*
to the console-free :mod:`sase.plugins.operations` layer and keeps only the
presentation concerns: a spinner, the Rich result panels, the stable
``-j|--json`` payloads, and the process exit codes. The flow follows the epic's
decisions: detect a managed ``uv tool install sase`` (*D4*); resolve the
``<plugin>`` name to a uv install spec; read sase's uv receipt as the source of
truth for the injected set (*D2*); if the plugin is already injected, render an
idempotent message and exit success; otherwise re-run ``uv tool install`` with
the **full** reconstructed ``--with`` set plus the new plugin (finding #2) and
render the result. ``-n|--dry-run`` previews the exact uv argv without executing
(*D5*); ``-j|--json`` emits a stable payload.

Every impure dependency (the install probe, the catalog loader, the uv runner,
the installed-inventory lookup) is injectable through to the operations layer,
so the whole handler is unit-testable without a real uv install.
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
from sase.plugins.installed import build_installed_index
from sase.plugins.operations import (
    AlreadyInstalled,
    ClockFn,
    InstallNotFound,
    InstallOutcome,
    InstallReady,
    InstalledIndexFn,
    LoadFn,
    NotUvTool,
    ProbeFn,
    ResolvedSpec,
    RunUvFn,
    execute_install,
    plan_install,
    resolve_install_spec,
)
from sase.plugins.render import (
    render_install_already_installed,
    render_install_dry_run,
    render_install_result,
    render_show_not_found,
)
from sase.plugins.cli_restart import restart_after_plugin_change
from sase.uv_tool.detect import probe_uv_tool_install
from sase.uv_tool.errors import ReceiptError, UvToolError
from sase.uv_tool.render import render_uv_tool_error
from sase.uv_tool.runner import ChangeKind, run_uv
from sase.version._utils import normalize_distribution_name

#: Bump when the ``-j|--json`` payload shape changes incompatibly.
INSTALL_JSON_SCHEMA_VERSION = 1

#: Re-exported for the existing CLI test-suite, which imports it by this name.
#: The implementation now lives in :mod:`sase.plugins.operations`.
_resolve_install_spec = resolve_install_spec


def handle_plugin_install_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    load_fn: LoadFn = load_plugin_catalog,
    probe_fn: ProbeFn = probe_uv_tool_install,
    run_fn: RunUvFn = run_uv,
    installed_index_fn: InstalledIndexFn = build_installed_index,
    axe_running_fn: AxeRunningFn = is_axe_running,
    restart_axe_fn: RestartAxeFn = restart_axe_daemon_result,
    clock: ClockFn = time.monotonic,
) -> int:
    """Run ``sase plugin install <plugin>``; return the process exit code."""
    query = str(getattr(args, "plugin", "") or "")
    git = bool(getattr(args, "git", False))
    refresh = bool(getattr(args, "refresh", False))
    dry_run = bool(getattr(args, "dry_run", False))
    as_json = bool(getattr(args, "json", False))
    out = console or Console()
    err = err_console or Console(stderr=True)

    try:
        plan = plan_install(
            query, git=git, refresh=refresh, load_fn=load_fn, probe_fn=probe_fn
        )
    except PluginCatalogError as exc:
        return _fail_catalog(exc, as_json=as_json, err=err)
    except ReceiptError as exc:
        return _fail(exc, as_json=as_json, err=err)

    if isinstance(plan, NotUvTool):
        return _fail(plan.error, as_json=as_json, err=err)
    if isinstance(plan, InstallNotFound):
        return _not_found(plan, as_json=as_json, err=err)
    if isinstance(plan, AlreadyInstalled):
        return _already_installed(plan.spec, as_json=as_json, out=out)

    if dry_run:
        return _dry_run(plan, as_json=as_json, out=out)

    use_spinner = not as_json and out.is_terminal
    try:
        if use_spinner:
            with out.status(
                f"Installing {plan.spec.display_name} via uv…", spinner="dots"
            ):
                outcome = execute_install(
                    plan,
                    run_fn=run_fn,
                    installed_index_fn=installed_index_fn,
                    clock=clock,
                )
        else:
            outcome = execute_install(
                plan,
                run_fn=run_fn,
                installed_index_fn=installed_index_fn,
                clock=clock,
            )
    except UvToolError as exc:
        return _fail(exc, as_json=as_json, err=err)

    restart = restart_after_plugin_change(
        outcome.change_set,
        axe_running_fn=axe_running_fn,
        restart_axe_fn=restart_axe_fn,
        source="sase plugin install",
    )

    if as_json:
        print(json.dumps(_result_json(outcome, restart), indent=2, sort_keys=True))
        from sase.ops.commands.plugin import emit_plugin_install_result

        emit_plugin_install_result(
            success=True,
            message=f"Installed {outcome.plan.spec.display_name}",
            payload={"plugin": outcome.plan.spec.display_name},
            args=args,
        )
        return 0

    render_install_result(
        dist_name=outcome.plan.spec.requirement.name,
        short_name=outcome.plan.spec.display_name,
        change_set=outcome.change_set,
        groups=outcome.groups,
        elapsed=outcome.elapsed,
        console=out,
    )
    render_restart_info(restart, console=out, quiet=False)
    from sase.ops.commands.plugin import emit_plugin_install_result

    emit_plugin_install_result(
        success=True,
        message=f"Installed {outcome.plan.spec.display_name}",
        payload={"plugin": outcome.plan.spec.display_name},
        args=args,
    )
    return 0


def _already_installed(spec: ResolvedSpec, *, as_json: bool, out: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": INSTALL_JSON_SCHEMA_VERSION,
                    "dry_run": False,
                    "already_installed": True,
                    "plugin": spec.display_name,
                    "distribution": spec.requirement.name,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    render_install_already_installed(
        dist_name=spec.requirement.name,
        short_name=spec.display_name,
        console=out,
    )
    return 0


def _dry_run(plan: InstallReady, *, as_json: bool, out: Console) -> int:
    spec = plan.spec
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": INSTALL_JSON_SCHEMA_VERSION,
                    "dry_run": True,
                    "command": list(plan.argv),
                    "plugin": spec.display_name,
                    "distribution": spec.requirement.name,
                    "source": spec.source,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    render_install_dry_run(
        argv=plan.argv,
        short_name=spec.display_name,
        source=spec.source,
        console=out,
    )
    return 0


def _not_found(plan: InstallNotFound, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": INSTALL_JSON_SCHEMA_VERSION,
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
                {"schema_version": INSTALL_JSON_SCHEMA_VERSION, "error": str(error)},
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
                {"schema_version": INSTALL_JSON_SCHEMA_VERSION, "error": str(error)},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        err.print(str(error))
    return 1


def _result_json(outcome: InstallOutcome, restart: RestartInfo) -> dict[str, Any]:
    spec = outcome.plan.spec
    change_set = outcome.change_set
    change = change_set.get(spec.requirement.name)
    return {
        "schema_version": INSTALL_JSON_SCHEMA_VERSION,
        "dry_run": False,
        "command": list(outcome.plan.argv),
        "plugin": spec.display_name,
        "distribution": spec.requirement.name,
        "source": spec.source,
        "version": change.new_version if change is not None else None,
        "entry_point_groups": list(outcome.groups),
        "elapsed_seconds": round(outcome.elapsed, 3),
        "restart": restart_info_json(restart),
        "dependencies_changed": sum(
            1
            for c in change_set.changes
            if normalize_distribution_name(c.name) != spec.normalized_name
            and c.kind is not ChangeKind.UNCHANGED
        ),
    }


__all__ = [
    "INSTALL_JSON_SCHEMA_VERSION",
    "handle_plugin_install_command",
]
