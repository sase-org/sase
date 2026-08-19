"""Rich and JSON presentation for ``sase tmux-agent``."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import replace
import difflib
from importlib import import_module
import json
import os
from pathlib import Path
import shlex
import sys
from typing import Any, cast

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.config.tmux_agent import (
    TmuxAgentConfig,
    TmuxAgentProviderConfig,
    get_tmux_agent_config,
)
from sase.llm_provider import effective_default_effort_snapshot
from sase.llm_provider import registry as llm_registry
from sase.llm_provider.types import LLMInvocationError

from .catalog import build_tmux_agent_catalog
from .launch import TmuxAgentLaunch, TmuxAgentLaunchError, launch_agent_window
from .launch_spec import (
    InvocationOptionProvider,
    resolve_effort_level,
    resolve_launch_argv,
)
from .menu import run_display_menu
from .models import TmuxAgentCatalog, TmuxAgentEntry
from .renumber import renumber_agent_windows
from .tmux import TmuxRunner, inside_tmux, tmux_available
from .window import next_window_name

TMUX_AGENT_JSON_SCHEMA_VERSION = 1
OUTSIDE_TMUX_MESSAGE = (
    "sase tmux-agent: not inside a tmux session; start tmux first, "
    "or use --list to see available agent CLIs."
)
TMUX_MISSING_MESSAGE = (
    "sase tmux-agent: tmux is not installed or not on PATH; install tmux, then retry."
)

CatalogFn = Callable[..., TmuxAgentCatalog]
ConfigFn = Callable[[], TmuxAgentConfig]
LaunchFn = Callable[..., TmuxAgentLaunch | TmuxAgentLaunchError]
MenuFn = Callable[..., Any]
OverrideFn = Callable[..., TmuxAgentEntry]
RefreshFn = Callable[[], None]
RenumberFn = Callable[..., int]
TmuxAvailableFn = Callable[[], bool]
InsideTmuxFn = Callable[..., bool]
CwdFn = Callable[[], str]


def handle_tmux_agent_cli(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    catalog_fn: CatalogFn = build_tmux_agent_catalog,
    config_fn: ConfigFn = get_tmux_agent_config,
    launch_fn: LaunchFn = launch_agent_window,
    menu_fn: MenuFn = run_display_menu,
    override_fn: OverrideFn | None = None,
    refresh_fn: RefreshFn | None = None,
    renumber_fn: RenumberFn = renumber_agent_windows,
    runner: TmuxRunner | None = None,
    tmux_available_fn: TmuxAvailableFn = tmux_available,
    inside_tmux_fn: InsideTmuxFn = inside_tmux,
    cwd_fn: CwdFn = os.getcwd,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Dispatch ``sase tmux-agent`` and return an exit code."""
    out = console or Console()
    tmux = runner or TmuxRunner()
    apply_overrides = override_fn or _apply_launch_overrides
    as_json = bool(getattr(args, "json", False))
    as_list = bool(getattr(args, "list", False))
    dry_run = bool(getattr(args, "dry_run", False))
    verbose = bool(getattr(args, "verbose", False))
    safe = bool(getattr(args, "safe", False))
    explicit_effort = getattr(args, "effort", None)
    provider = getattr(args, "provider", None)

    if getattr(args, "renumber", False):
        return _handle_renumber(
            config_fn=config_fn,
            runner=tmux,
            renumber_fn=renumber_fn,
            tmux_available_fn=tmux_available_fn,
            inside_tmux_fn=inside_tmux_fn,
            environ=environ,
        )

    if getattr(args, "refresh", False):
        (refresh_fn or _default_refresh)()

    directory = _resolve_directory(
        getattr(args, "directory", None),
        runner=tmux,
        tmux_available_fn=tmux_available_fn,
        inside_tmux_fn=inside_tmux_fn,
        cwd_fn=cwd_fn,
        environ=environ,
    )

    try:
        catalog = catalog_fn(directory=directory)
    except Exception as exc:  # noqa: BLE001 - CLI boundary must remain actionable.
        return _error(
            f"sase tmux-agent: could not build catalog: {exc}",
            as_json=as_json,
            code=1,
        )

    if as_json and not dry_run:
        print(json.dumps(_catalog_json(catalog), indent=2, sort_keys=True))
        return 0
    if as_list and not dry_run:
        _render_catalog(catalog, verbose=verbose, console=out)
        return 0
    if dry_run:
        return _handle_dry_run(
            catalog,
            provider=provider,
            explicit_effort=explicit_effort,
            safe=safe,
            as_json=as_json,
            config_fn=config_fn,
            override_fn=apply_overrides,
            runner=tmux,
            tmux_available_fn=tmux_available_fn,
            inside_tmux_fn=inside_tmux_fn,
            environ=environ,
            console=out,
        )

    if not tmux_available_fn():
        return _error(TMUX_MISSING_MESSAGE, as_json=as_json, code=2)
    if not inside_tmux_fn(environ):
        print(OUTSIDE_TMUX_MESSAGE, file=sys.stderr)
        _render_catalog(catalog, verbose=verbose, console=out)
        return 2

    if provider:
        return _handle_launch(
            catalog,
            provider=provider,
            directory=directory,
            explicit_effort=explicit_effort,
            safe=safe,
            as_json=as_json,
            config_fn=config_fn,
            override_fn=apply_overrides,
            launch_fn=launch_fn,
            runner=tmux,
        )
    return _handle_menu(catalog, menu_fn=menu_fn, runner=tmux)


def _default_refresh() -> None:
    """Rebuild the catalog cache when the cache phase has landed."""
    try:
        cache_mod = import_module("sase.tmux_agent.cache")
    except ImportError:
        return
    refresh = getattr(cache_mod, "refresh_catalog_cache", None)
    if callable(refresh):
        refresh()


def _handle_renumber(
    *,
    config_fn: ConfigFn,
    runner: TmuxRunner,
    renumber_fn: RenumberFn,
    tmux_available_fn: TmuxAvailableFn,
    inside_tmux_fn: InsideTmuxFn,
    environ: Mapping[str, str] | None,
) -> int:
    try:
        if not tmux_available_fn() or not inside_tmux_fn(environ):
            return 0
        renumber_fn(config=config_fn(), runner=runner)
    except Exception:  # noqa: BLE001 - background hook must stay silent.
        return 0
    return 0


def _handle_menu(
    catalog: TmuxAgentCatalog,
    *,
    menu_fn: MenuFn,
    runner: TmuxRunner,
) -> int:
    result = menu_fn(catalog, runner=runner, title="tmux Agent")
    if getattr(result, "returncode", 0) == 0:
        return 0
    detail = getattr(result, "stderr", None) or getattr(result, "stdout", None) or ""
    detail = str(detail).strip() or "unknown tmux error"
    print(f"sase tmux-agent: tmux display-menu failed: {detail}", file=sys.stderr)
    return 2


def _handle_launch(
    catalog: TmuxAgentCatalog,
    *,
    provider: str,
    directory: str,
    explicit_effort: str | None,
    safe: bool,
    as_json: bool,
    config_fn: ConfigFn,
    override_fn: OverrideFn,
    launch_fn: LaunchFn,
    runner: TmuxRunner,
) -> int:
    entry, code = _resolve_provider(
        catalog,
        provider,
        explicit_effort=explicit_effort,
        safe=safe,
        as_json=as_json,
        override_fn=override_fn,
        require_installed=True,
    )
    if entry is None:
        return code
    result = launch_fn(
        entry,
        directory=directory,
        config=config_fn(),
        runner=runner,
    )
    if isinstance(result, TmuxAgentLaunchError):
        code = 1 if result.code == "not_installed" else 2
        return _error(
            f"sase tmux-agent: {result.message}",
            as_json=as_json,
            code=code,
            extra={"provider": entry.provider, "error_code": result.code},
        )
    print(f"sase_tmux_agent_window={result.window_name}")
    print(f"sase_tmux_agent_provider={entry.provider}")
    return 0


def _handle_dry_run(
    catalog: TmuxAgentCatalog,
    *,
    provider: str | None,
    explicit_effort: str | None,
    safe: bool,
    as_json: bool,
    config_fn: ConfigFn,
    override_fn: OverrideFn,
    runner: TmuxRunner,
    tmux_available_fn: TmuxAvailableFn,
    inside_tmux_fn: InsideTmuxFn,
    environ: Mapping[str, str] | None,
    console: Console,
) -> int:
    target = provider or catalog.default_provider
    if not target:
        return _error(
            "sase tmux-agent: --dry-run needs a provider (or an installed default)",
            as_json=as_json,
            code=2,
        )
    entry, code = _resolve_provider(
        catalog,
        target,
        explicit_effort=explicit_effort,
        safe=safe,
        as_json=as_json,
        override_fn=override_fn,
        require_installed=False,
    )
    if entry is None:
        return code
    config = config_fn()
    windows: tuple[str, ...] = ()
    if tmux_available_fn() and inside_tmux_fn(environ):
        windows = tuple(name for _index, name in runner.list_windows())
    window_name = next_window_name(config.window_name, windows)
    payload = _dry_run_json(entry, window_name=window_name, directory=catalog.directory)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    env_text = " ".join(f"{key}={value}" for key, value in entry.env) or "(none)"
    console.print(f"window: {window_name}")
    console.print(f"directory: {catalog.directory}")
    console.print(f"env: {env_text}")
    console.print(f"command: {shlex.join(entry.argv)}")
    return 0


def _resolve_provider(
    catalog: TmuxAgentCatalog,
    query: str,
    *,
    explicit_effort: str | None,
    safe: bool,
    as_json: bool,
    override_fn: OverrideFn,
    require_installed: bool,
) -> tuple[TmuxAgentEntry | None, int]:
    entry = _find_entry(catalog, query)
    if entry is None:
        return None, _unknown_provider(query, catalog, as_json=as_json)
    try:
        entry = override_fn(entry, explicit_effort=explicit_effort, safe=safe)
    except LLMInvocationError as exc:
        return None, _error(
            f"sase tmux-agent: {exc}",
            as_json=as_json,
            code=2,
            extra={"provider": entry.provider},
        )
    if require_installed and not entry.installed:
        hint = entry.install_hint.strip()
        message = f"sase tmux-agent: {entry.display_name} is not installed."
        if hint:
            message = f"{message} {hint}"
        return None, _error(
            message,
            as_json=as_json,
            code=1,
            extra={
                "provider": entry.provider,
                "install_hint": entry.install_hint,
            },
        )
    return entry, 0


def _apply_launch_overrides(
    entry: TmuxAgentEntry,
    *,
    explicit_effort: str | None = None,
    safe: bool = False,
) -> TmuxAgentEntry:
    """Rebuild one entry's argv when ``-e/--effort`` or ``-s/--safe`` is set."""
    if explicit_effort is None and not safe:
        return entry

    config = get_tmux_agent_config()
    provider_config = config.providers.get(entry.provider, TmuxAgentProviderConfig())
    if safe:
        provider_config = replace(provider_config, bypass_permissions=False)

    if explicit_effort is not None:
        effort_level = None if explicit_effort == "off" else explicit_effort
        explicit = True
    else:
        effort_level = resolve_effort_level(
            provider_effort=provider_config.effort,
            catalog_effort=config.effort,
            default_effort=effective_default_effort_snapshot().effective_effort(),
        )
        explicit = False

    descriptor = llm_registry.provider_interactive_cli_map().get(entry.provider) or {}
    provider_obj = cast(
        "dict[str, InvocationOptionProvider]",
        dict(llm_registry.iter_plugins()),
    ).get(entry.provider)
    spec = resolve_launch_argv(
        entry.provider,
        descriptor=descriptor,
        provider_config=provider_config,
        catalog_config=config,
        effort=effort_level,
        provider_obj=provider_obj,
        explicit=explicit,
    )
    return replace(
        entry,
        argv=spec.argv,
        env=spec.env,
        effort=spec.effort,
        effort_skipped=spec.effort_skipped,
        bypass=spec.bypass,
    )


def _resolve_directory(
    raw: str | None,
    *,
    runner: TmuxRunner,
    tmux_available_fn: TmuxAvailableFn,
    inside_tmux_fn: InsideTmuxFn,
    cwd_fn: CwdFn,
    environ: Mapping[str, str] | None,
) -> str:
    if raw:
        return str(Path(raw).expanduser())
    if tmux_available_fn() and inside_tmux_fn(environ):
        pane = runner.current_pane_directory()
        if pane:
            return pane
    return cwd_fn()


def _find_entry(catalog: TmuxAgentCatalog, query: str) -> TmuxAgentEntry | None:
    key = _name_key(query)
    for entry in catalog.entries:
        if key in {
            _name_key(entry.provider),
            _name_key(entry.binary),
            _name_key(entry.display_name),
        }:
            return entry
    return None


def _name_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _unknown_provider(
    query: str,
    catalog: TmuxAgentCatalog,
    *,
    as_json: bool,
) -> int:
    known = [entry.provider for entry in catalog.entries]
    suggestions = difflib.get_close_matches(query, known, n=1, cutoff=0.5)
    if known:
        message = (
            f"sase tmux-agent: unknown provider {query!r}; known: {', '.join(known)}"
        )
    else:
        message = (
            f"sase tmux-agent: unknown provider {query!r}; no agent CLIs are available"
        )
    extra = {
        "query": query,
        "known_providers": known,
        "suggestions": suggestions,
    }
    if as_json:
        return _error(message, as_json=True, code=2, extra=extra)
    print(message, file=sys.stderr)
    if suggestions:
        print(f"Did you mean: {', '.join(suggestions)}?", file=sys.stderr)
    return 2


def _error(
    message: str,
    *,
    as_json: bool,
    code: int,
    extra: Mapping[str, Any] | None = None,
) -> int:
    if as_json:
        payload: dict[str, Any] = {
            "schema_version": TMUX_AGENT_JSON_SCHEMA_VERSION,
            "error": message,
        }
        if extra:
            payload.update(extra)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return code
    print(message, file=sys.stderr)
    return code


def _catalog_json(catalog: TmuxAgentCatalog) -> dict[str, Any]:
    entries = [_entry_json(entry) for entry in catalog.entries]
    return {
        "schema_version": TMUX_AGENT_JSON_SCHEMA_VERSION,
        "directory": catalog.directory,
        "default_provider": catalog.default_provider,
        "counts": {
            "installed": sum(entry.installed for entry in catalog.entries),
            "not_installed": sum(not entry.installed for entry in catalog.entries),
            "routing_disabled": sum(
                entry.routing_disabled is not None for entry in catalog.entries
            ),
            "total": len(catalog.entries),
        },
        "entries": entries,
    }


def _entry_json(entry: TmuxAgentEntry) -> dict[str, Any]:
    disable = entry.routing_disabled
    return {
        "provider": entry.provider,
        "display_name": entry.display_name,
        "vendor": entry.vendor,
        "color": entry.color,
        "key": entry.key,
        "binary": entry.binary,
        "executable": entry.executable,
        "installed": entry.installed,
        "install_hint": entry.install_hint,
        "routing_disabled": None
        if disable is None
        else {
            "provider": disable.provider,
            "expires_at": disable.expires_at,
            "source": disable.source,
            "mode": disable.mode,
        },
        "argv": list(entry.argv),
        "command": shlex.join(entry.argv),
        "env": dict(entry.env),
        "effort": entry.effort,
        "effort_skipped": entry.effort_skipped,
        "bypass": entry.bypass,
    }


def _dry_run_json(
    entry: TmuxAgentEntry, *, window_name: str, directory: str
) -> dict[str, Any]:
    return {
        "schema_version": TMUX_AGENT_JSON_SCHEMA_VERSION,
        "dry_run": True,
        "provider": entry.provider,
        "display_name": entry.display_name,
        "window_name": window_name,
        "directory": directory,
        "installed": entry.installed,
        "argv": list(entry.argv),
        "command": shlex.join(entry.argv),
        "env": dict(entry.env),
        "effort": entry.effort,
        "effort_skipped": entry.effort_skipped,
        "bypass": entry.bypass,
    }


def _render_catalog(
    catalog: TmuxAgentCatalog,
    *,
    verbose: bool,
    console: Console,
) -> None:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("KEY", no_wrap=True)
    table.add_column("CLI", no_wrap=True)
    table.add_column("VENDOR")
    table.add_column("STATUS")
    if verbose:
        table.add_column("DETAILS")

    for entry in catalog.entries:
        row: list[Text] = [
            Text(entry.key or "—", style="bold"),
            Text(entry.display_name, style=_name_style(entry)),
            Text(entry.vendor, style="dim"),
            _status_cell(entry),
        ]
        if verbose:
            row.append(_details_cell(entry))
        table.add_row(*row)

    installed_count = sum(entry.installed for entry in catalog.entries)
    summary = Text()
    summary.append(
        f"{installed_count}/{len(catalog.entries)} installed",
        style="dim",
    )
    if catalog.default_provider:
        summary.append("  ·  ", style="dim")
        summary.append(f"default: {catalog.default_provider}", style="dim")
    summary.append("  ·  ", style="dim")
    summary.append(catalog.directory, style="dim")

    console.print(
        Panel(
            Group(table, Text(""), summary),
            title="tmux Agent",
            border_style="cyan",
        )
    )


def _name_style(entry: TmuxAgentEntry) -> str:
    if not entry.installed:
        return "dim"
    return entry.color or "bold cyan"


def _status_cell(entry: TmuxAgentEntry) -> Text:
    if not entry.installed:
        return Text("not installed", style="yellow")
    if entry.routing_disabled is not None:
        return Text("routing disabled", style="yellow")
    return Text("ready", style="green")


def _details_cell(entry: TmuxAgentEntry) -> Text:
    details = Text(entry.executable or "—", style="dim")
    details.append("\n")
    details.append(shlex.join(entry.argv) or entry.binary, style="dim")
    if not entry.installed and entry.install_hint:
        details.append("\n")
        details.append(entry.install_hint, style="yellow")
    elif entry.effort_skipped:
        details.append("\n")
        details.append(
            f"skipped unsupported effort {entry.effort_skipped!r}",
            style="yellow",
        )
    return details


__all__ = [
    "OUTSIDE_TMUX_MESSAGE",
    "TMUX_AGENT_JSON_SCHEMA_VERSION",
    "TMUX_MISSING_MESSAGE",
    "handle_tmux_agent_cli",
]
