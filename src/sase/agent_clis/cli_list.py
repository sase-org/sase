"""Rich and JSON presentation for ``sase agent-cli list``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import AgentCliStatus, InstallMethod
from .operations import collect_agent_cli_statuses

LIST_AGENT_CLI_JSON_SCHEMA_VERSION = 1

StatusFn = Callable[..., tuple[AgentCliStatus, ...]]


def handle_agent_cli_list_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    status_fn: StatusFn = collect_agent_cli_statuses,
) -> int:
    """Load and present the supported agent-CLI inventory."""
    offline = bool(getattr(args, "offline", False))
    refresh = bool(getattr(args, "refresh", False))
    verbose = bool(getattr(args, "verbose", False))
    as_json = bool(getattr(args, "json", False))
    out = console or Console()
    err = err_console or Console(stderr=True)

    try:
        statuses = status_fn(refresh=refresh, offline=offline)
    except Exception as exc:  # noqa: BLE001 - CLI boundary must remain actionable.
        message = f"Could not inspect agent CLIs: {exc}"
        if as_json:
            print(
                json.dumps(
                    {
                        "schema_version": LIST_AGENT_CLI_JSON_SCHEMA_VERSION,
                        "error": message,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            err.print(Text(message, style="bold red"))
            err.print(
                "Canonical provider documentation is available with "
                "[bold]sase agent-cli list -v[/bold]."
            )
        return 1

    if as_json:
        print(json.dumps(_build_list_json(statuses), indent=2, sort_keys=True))
        return 0

    _render_statuses(statuses, verbose=verbose, console=out)
    return 0


def _build_list_json(statuses: Sequence[AgentCliStatus]) -> dict[str, Any]:
    """Build the versioned JSON envelope for the agent-CLI inventory."""
    entries = [_status_json(status) for status in statuses]
    return {
        "schema_version": LIST_AGENT_CLI_JSON_SCHEMA_VERSION,
        "counts": {
            "installed": sum(status.installed for status in statuses),
            "not_installed": sum(not status.installed for status in statuses),
            "total": len(statuses),
            "updates_available": sum(status.update_available for status in statuses),
        },
        "agent_clis": entries,
    }


def _status_json(status: AgentCliStatus) -> dict[str, Any]:
    return {
        "name": status.name,
        "display_name": status.display_name,
        "binary": status.binary,
        "installed": status.installed,
        "executable": status.executable,
        "installed_version": status.installed_version,
        "latest_version": status.latest_version,
        "install_method": status.install_method.value,
        "update_available": status.update_available,
        "install_hint": status.install_hint,
        "docs_url": status.docs_url,
        "errors": {
            "version": status.version_error,
            "latest": status.latest_error,
        },
    }


def _render_statuses(
    statuses: Sequence[AgentCliStatus],
    *,
    verbose: bool,
    console: Console,
) -> None:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("CLI", style="bold", no_wrap=True)
    table.add_column("BINARY", no_wrap=True)
    table.add_column("INSTALLED")
    table.add_column("LATEST", no_wrap=True)
    table.add_column("METHOD", no_wrap=True)
    table.add_column("", no_wrap=True)
    if verbose:
        table.add_column("PATH / DOCS")

    for status in statuses:
        row: list[Text] = [
            Text(status.display_name, style="bold cyan"),
            Text(status.binary),
            _installed_cell(status),
            _latest_cell(status),
            _method_cell(status.install_method),
            Text("↑", style="bold cyan") if status.update_available else Text(""),
        ]
        if verbose:
            row.append(_details_cell(status))
        table.add_row(*row)

    installed_count = sum(status.installed for status in statuses)
    update_count = sum(status.update_available for status in statuses)
    summary = Text()
    summary.append(f"{installed_count}/{len(statuses)} installed", style="dim")
    summary.append("  ·  ", style="dim")
    if update_count:
        summary.append(f"{update_count} update", style="bold cyan")
        summary.append("s" if update_count != 1 else "", style="bold cyan")
        summary.append(" available", style="bold cyan")
    else:
        summary.append("no known updates", style="green")

    console.print(
        Panel(
            Group(table, Text(""), summary),
            title="Agent CLIs",
            border_style="cyan",
        )
    )


def _installed_cell(status: AgentCliStatus) -> Text:
    if status.install_method is InstallMethod.NOT_INSTALLED:
        value = Text("not installed", style="yellow")
        value.append("\n")
        value.append(status.install_hint, style="dim")
        return value
    if status.install_method is InstallMethod.BUNDLED:
        return Text(status.installed_version or "bundled", style="green")
    if status.installed_version:
        return Text(status.installed_version, style="green")
    value = Text("installed; version unknown", style="yellow")
    if status.version_error:
        value.append("\n")
        value.append(status.version_error, style="dim")
    return value


def _latest_cell(status: AgentCliStatus) -> Text:
    if status.latest_version:
        style = "bold cyan" if status.update_available else "green"
        return Text(status.latest_version, style=style)
    if status.latest_error == "offline":
        return Text("unknown (offline)", style="dim")
    if status.latest_error == "offline_stale_cache":
        return Text("unknown (stale cache)", style="dim")
    return Text("unknown", style="dim")


def _method_cell(method: InstallMethod) -> Text:
    styles = {
        InstallMethod.NPM: "magenta",
        InstallMethod.HOMEBREW: "blue",
        InstallMethod.SELF_MANAGED: "cyan",
        InstallMethod.BUNDLED: "green",
        InstallMethod.NOT_INSTALLED: "dim",
        InstallMethod.UNKNOWN: "yellow",
    }
    return Text(method.value.replace("_", " "), style=styles[method])


def _details_cell(status: AgentCliStatus) -> Text:
    details = Text(status.executable or "—", style="dim")
    if status.docs_url:
        details.append("\n")
        details.append(status.docs_url, style="blue underline")
    if (
        status.version_error
        and status.install_method is not InstallMethod.NOT_INSTALLED
    ):
        details.append("\nversion: ", style="dim")
        details.append(status.version_error, style="yellow")
    if status.latest_error:
        details.append("\nlatest: ", style="dim")
        details.append(status.latest_error, style="yellow")
    return details


__all__ = [
    "LIST_AGENT_CLI_JSON_SCHEMA_VERSION",
    "handle_agent_cli_list_command",
]
