"""Orchestration for ``sase plugin update <plugin>`` / ``--all``.

Like :mod:`sase.plugins.cli_install`, this joins the plugin catalog to the shared
``uv tool`` engine. It detects a managed ``uv tool install sase`` (*D4*), reads
sase's uv receipt as the source of truth for the injected set (*D2*), and upgrades
the requested plugin(s) with ``uv tool install <full set> --upgrade-package <name>``
— upgrading only the named plugins while leaving sase core and every other plugin
pinned (decision *D3*'s complement: "update plugins" never silently bumps core).
``-a|--all`` upgrades every injected plugin in one shot; ``-n|--dry-run`` previews
the uv argv; ``-j|--json`` emits a stable payload.

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

from sase.plugins.catalog import (
    PluginCatalog,
    PluginCatalogError,
    find_plugin,
    load_plugin_catalog,
    suggest_plugins,
)
from sase.plugins.render import (
    render_no_plugins_installed,
    render_plugin_not_installed,
    render_plugin_update_dry_run,
    render_plugin_update_result,
    render_show_not_found,
)
from sase.uv_tool.commands import build_upgrade_packages
from sase.uv_tool.detect import (
    NotUvToolInstall,
    UvToolInstall,
    probe_uv_tool_install,
)
from sase.uv_tool.errors import NotAUvToolInstallError, ReceiptError, UvToolError
from sase.uv_tool.receipt import Requirement, ToolReceipt, load_receipt
from sase.uv_tool.render import render_uv_tool_error
from sase.uv_tool.runner import ChangeKind, UvChangeSet, run_uv
from sase.version._utils import normalize_distribution_name

#: Bump when the ``-j|--json`` payload shape changes incompatibly.
UPDATE_PLUGIN_JSON_SCHEMA_VERSION = 1

LoadFn = Callable[..., PluginCatalog]
ProbeFn = Callable[[], UvToolInstall | NotUvToolInstall]
RunUvFn = Callable[[list[str]], UvChangeSet]
VersionFn = Callable[[str], str | None]
ClockFn = Callable[[], float]


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

    install = probe_fn()
    if isinstance(install, NotUvToolInstall):
        return _fail(NotAUvToolInstallError(install), as_json=as_json, err=err)

    try:
        receipt = load_receipt(install.receipt_path)
    except ReceiptError as exc:
        return _fail(exc, as_json=as_json, err=err)

    if all_plugins:
        targets = tuple(plugin.name for plugin in receipt.deduped_injected_plugins())
        if not targets:
            return _no_plugins(as_json=as_json, out=out)
    else:
        try:
            resolved = _resolve_target(
                receipt, str(query), load_fn=load_fn, refresh=refresh
            )
        except PluginCatalogError as exc:
            return _fail_catalog(exc, as_json=as_json, err=err)
        if isinstance(resolved, _Unknown):
            return _not_found(resolved.catalog, str(query), as_json=as_json, err=err)
        if isinstance(resolved, _NotInstalled):
            return _not_installed(resolved.name, as_json=as_json, err=err)
        targets = (resolved.name,)

    argv = build_upgrade_packages(receipt, targets, color="never")
    if dry_run:
        return _dry_run(
            argv, targets, all_plugins=all_plugins, as_json=as_json, out=out
        )

    use_spinner = not as_json and out.is_terminal
    start = clock()
    try:
        if use_spinner:
            with out.status("Upgrading plugins via uv…", spinner="dots"):
                change_set = run_fn(argv)
        else:
            change_set = run_fn(argv)
    except UvToolError as exc:
        return _fail(exc, as_json=as_json, err=err)
    elapsed = max(0.0, clock() - start)

    if as_json:
        print(
            json.dumps(
                _result_json(argv, targets, change_set, elapsed, version_fn),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    render_plugin_update_result(
        change_set=change_set,
        dist_names=targets,
        all_plugins=all_plugins,
        elapsed=elapsed,
        current_version=version_fn,
        console=out,
    )
    return 0


# --------------------------------------------------------------------------- #
# Target resolution
# --------------------------------------------------------------------------- #


class _NotInstalled:
    """The plugin exists in the catalog but is not injected into sase's env."""

    def __init__(self, name: str) -> None:
        self.name = name


class _Unknown:
    """The plugin name matched nothing — caller renders ranked suggestions."""

    def __init__(self, catalog: PluginCatalog) -> None:
        self.catalog = catalog


def _resolve_target(
    receipt: ToolReceipt,
    query: str,
    *,
    load_fn: LoadFn,
    refresh: bool,
) -> Requirement | _NotInstalled | _Unknown:
    """Resolve *query* to an injected plugin, or explain why it is not one.

    Tries the receipt first (no catalog fetch) so an installed plugin — even a
    community one absent from the catalog — resolves directly. Only on a miss is
    the catalog loaded, to separate "known but not installed" from "unknown".
    """
    injected = _match_injected(receipt, query)
    if injected is not None:
        return injected

    catalog = load_fn(refresh=refresh)
    entry = find_plugin(catalog, query)
    if entry is not None:
        return _NotInstalled(entry.name)
    return _Unknown(catalog)


def _match_injected(receipt: ToolReceipt, query: str) -> Requirement | None:
    for candidate in _name_candidates(query):
        key = normalize_distribution_name(candidate)
        if not key:
            continue
        for plugin in receipt.deduped_injected_plugins():
            if plugin.normalized_name == key:
                return plugin
    return None


def _name_candidates(query: str) -> tuple[str, ...]:
    base = query.strip()
    short = base.split("/", 1)[1] if "/" in base else base
    candidates = [base, short]
    for value in (base, short):
        if value and not value.lower().startswith("sase-"):
            candidates.append(f"sase-{value}")
    return tuple(candidates)


# --------------------------------------------------------------------------- #
# Rendering / JSON helpers
# --------------------------------------------------------------------------- #


def _dry_run(
    argv: list[str],
    targets: tuple[str, ...],
    *,
    all_plugins: bool,
    as_json: bool,
    out: Console,
) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_PLUGIN_JSON_SCHEMA_VERSION,
                    "dry_run": True,
                    "all": all_plugins,
                    "command": list(argv),
                    "plugins": list(targets),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    render_plugin_update_dry_run(
        argv=argv, dist_names=targets, all_plugins=all_plugins, console=out
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


def _not_found(
    catalog: PluginCatalog,
    query: str,
    *,
    as_json: bool,
    err: Console,
) -> int:
    suggestions = suggest_plugins(catalog, query)
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_PLUGIN_JSON_SCHEMA_VERSION,
                    "found": False,
                    "query": query,
                    "suggestions": [entry.name for entry in suggestions],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    render_show_not_found(query, suggestions, console=err)
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
    argv: list[str],
    targets: tuple[str, ...],
    change_set: UvChangeSet,
    elapsed: float,
    version_fn: VersionFn,
) -> dict[str, Any]:
    plugins = []
    for name in targets:
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
        "command": list(argv),
        "changed": upgraded > 0,
        "elapsed_seconds": round(elapsed, 3),
        "counts": {"updated": upgraded, "already_current": len(plugins) - upgraded},
        "plugins": plugins,
    }


__all__ = [
    "UPDATE_PLUGIN_JSON_SCHEMA_VERSION",
    "handle_plugin_update_command",
]
