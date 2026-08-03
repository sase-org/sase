"""Rich and JSON presentation for ``sase agent-cli update``."""

from __future__ import annotations

import argparse
import json
import shlex
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .models import (
    AgentCliNothingToUpdate,
    AgentCliUnknownName,
    AgentCliUpdateEntry,
    AgentCliUpdatePlan,
    AgentCliUpdateResult,
    AgentCliUpdatesReady,
    UpdateResultStatus,
    UpdateTrigger,
)
from .operations import execute_agent_cli_updates, plan_agent_cli_updates

UPDATE_AGENT_CLI_JSON_SCHEMA_VERSION = 1

PlanFn = Callable[..., AgentCliUpdatePlan]
ExecuteFn = Callable[..., tuple[AgentCliUpdateResult, ...]]


def handle_agent_cli_update_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    plan_fn: PlanFn = plan_agent_cli_updates,
    execute_fn: ExecuteFn = execute_agent_cli_updates,
) -> int:
    """Plan, optionally preview, and execute agent-CLI updates."""
    names = tuple(getattr(args, "names", ()) or ())
    all_clis = bool(getattr(args, "all", False))
    as_json = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))
    offline = bool(getattr(args, "offline", False))
    refresh = bool(getattr(args, "refresh", False))
    out = console or Console()
    err = err_console or Console(stderr=True)

    if not all_clis and not names:
        return _usage_error(as_json=as_json, err=err)

    try:
        plan = plan_fn(
            names,
            all_clis=all_clis,
            refresh=refresh,
            offline=offline,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary must remain actionable.
        return _operation_error(
            f"Could not plan agent CLI updates: {exc}",
            as_json=as_json,
            err=err,
        )

    if isinstance(plan, AgentCliUnknownName):
        return _unknown_name(plan, as_json=as_json, err=err)

    if dry_run:
        if as_json:
            print(json.dumps(_dry_run_json(plan), indent=2, sort_keys=True))
        else:
            _render_dry_run(plan.entries, console=out)
        return 0

    try:
        results = execute_fn(plan, trigger=UpdateTrigger.CLI)
    except Exception as exc:  # noqa: BLE001 - preserve a stable CLI failure shape.
        return _operation_error(
            f"Could not execute agent CLI updates: {exc}",
            as_json=as_json,
            err=err,
            docs_urls=_docs_urls(plan.entries),
        )

    if as_json:
        print(
            json.dumps(
                _result_json(results, all_clis=plan.all_clis),
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _render_results(results, console=out)
    return (
        1
        if any(result.status is UpdateResultStatus.FAILED for result in results)
        else 0
    )


def _dry_run_json(
    plan: AgentCliUpdatesReady | AgentCliNothingToUpdate,
) -> dict[str, Any]:
    ready = sum(entry.ready for entry in plan.entries)
    return {
        "schema_version": UPDATE_AGENT_CLI_JSON_SCHEMA_VERSION,
        "dry_run": True,
        "all": plan.all_clis,
        "counts": {
            "ready": ready,
            "skipped": len(plan.entries) - ready,
            "total": len(plan.entries),
        },
        "agent_clis": [_plan_entry_json(entry) for entry in plan.entries],
    }


def _plan_entry_json(entry: AgentCliUpdateEntry) -> dict[str, Any]:
    status = entry.status
    return {
        "name": status.name,
        "display_name": status.display_name,
        "strategy": entry.strategy.value,
        "command": list(entry.argv) if entry.argv else None,
        "suggested_command": list(entry.manual_argv) if entry.manual_argv else None,
        "reason": _reason_with_docs(entry.skip_reason, status.docs_url),
        "docs_url": status.docs_url,
        "installed_version": status.installed_version,
        "latest_version": status.latest_version,
        "ready": entry.ready,
    }


def _result_json(
    results: Sequence[AgentCliUpdateResult], *, all_clis: bool
) -> dict[str, Any]:
    counts = Counter(result.status.value for result in results)
    return {
        "schema_version": UPDATE_AGENT_CLI_JSON_SCHEMA_VERSION,
        "dry_run": False,
        "all": all_clis,
        "counts": {status.value: counts[status.value] for status in UpdateResultStatus},
        "agent_clis": [_result_entry_json(result) for result in results],
    }


def _result_entry_json(result: AgentCliUpdateResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "display_name": result.display_name,
        "status": result.status.value,
        "old_version": result.old_version,
        "new_version": result.new_version,
        "command": list(result.command) if result.command else None,
        "suggested_command": (
            list(result.suggested_command) if result.suggested_command else None
        ),
        "elapsed_seconds": round(result.elapsed, 3),
        "reason": _reason_with_docs(result.reason, result.docs_url),
        "output_tail": result.output_tail,
        "docs_url": result.docs_url,
    }


def _render_dry_run(
    entries: Sequence[AgentCliUpdateEntry], *, console: Console
) -> None:
    body = Text()
    if not entries:
        body.append("No supported agent CLIs were found.", style="yellow")
    for index, entry in enumerate(entries):
        if index:
            body.append("\n")
        if entry.argv:
            body.append("● ", style="bold cyan")
            body.append(entry.status.display_name, style="bold")
            body.append("\n  ")
            body.append(shlex.join(entry.argv), style="cyan")
        else:
            body.append("○ ", style="yellow")
            body.append(entry.status.display_name, style="bold")
            body.append(" — ")
            body.append(
                _reason_with_docs(entry.skip_reason, entry.status.docs_url)
                or "skipped",
                style="yellow",
            )
            if entry.manual_argv:
                body.append("\n  manual: ", style="dim")
                body.append(shlex.join(entry.manual_argv), style="cyan")

    console.print(
        Panel(
            body,
            title="Agent CLI update preview",
            subtitle="Dry run · no commands executed",
            border_style="cyan",
        )
    )


def _render_results(
    results: Sequence[AgentCliUpdateResult], *, console: Console
) -> None:
    body = Text()
    if not results:
        body.append("No supported agent CLIs were selected.", style="yellow")
    for index, result in enumerate(results):
        if index:
            body.append("\n")
        glyph, style, label = {
            UpdateResultStatus.UPDATED: ("✓", "green", "updated"),
            UpdateResultStatus.ALREADY_CURRENT: ("✓", "cyan", "already current"),
            UpdateResultStatus.FAILED: ("✗", "bold red", "failed"),
            UpdateResultStatus.SKIPPED: ("○", "yellow", "skipped"),
        }[result.status]
        body.append(f"{glyph} ", style=style)
        body.append(result.display_name, style="bold")
        body.append(f" — {label}", style=style)
        if result.status is UpdateResultStatus.UPDATED:
            body.append(
                f" ({_version(result.old_version)} → {_version(result.new_version)})",
                style="green",
            )
        if result.command:
            body.append("\n  command: ", style="dim")
            body.append(shlex.join(result.command), style="cyan")
        if result.suggested_command:
            body.append("\n  manual: ", style="dim")
            body.append(shlex.join(result.suggested_command), style="cyan")
        reason = _reason_with_docs(result.reason, result.docs_url)
        if reason:
            body.append("\n  ")
            body.append(
                reason,
                style="red" if result.status is UpdateResultStatus.FAILED else "yellow",
            )
        if result.output_tail and result.status is UpdateResultStatus.FAILED:
            body.append("\n  output: ", style="dim")
            body.append(result.output_tail, style="dim")

    counts = Counter(result.status.value for result in results)
    subtitle = " · ".join(
        f"{counts[status.value]} {label}"
        for status, label in (
            (UpdateResultStatus.UPDATED, "updated"),
            (UpdateResultStatus.ALREADY_CURRENT, "current"),
            (UpdateResultStatus.SKIPPED, "skipped"),
            (UpdateResultStatus.FAILED, "failed"),
        )
        if counts[status.value]
    )
    console.print(
        Panel(
            body,
            title="Agent CLI updates",
            subtitle=subtitle or "No changes",
            border_style="red" if counts[UpdateResultStatus.FAILED.value] else "green",
        )
    )


def _usage_error(*, as_json: bool, err: Console) -> int:
    message = (
        "Specify one or more agent CLIs to update, or pass -a|--all to update "
        "every safe candidate."
    )
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_AGENT_CLI_JSON_SCHEMA_VERSION,
                    "error": message,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        err.print(Text(message, style="bold red"))
    return 2


def _unknown_name(plan: AgentCliUnknownName, *, as_json: bool, err: Console) -> int:
    message = f"Unknown agent CLI: {plan.query}"
    docs_pointer = (
        "Run `sase agent-cli list -v` for known names and canonical provider "
        "documentation URLs."
    )
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_AGENT_CLI_JSON_SCHEMA_VERSION,
                    "error": message,
                    "query": plan.query,
                    "known_names": list(plan.known_names),
                    "suggestions": list(plan.suggestions),
                    "docs": docs_pointer,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        err.print(Text(message, style="bold red"))
        if plan.suggestions:
            err.print(f"Did you mean: {', '.join(plan.suggestions)}?")
        elif plan.known_names:
            err.print(f"Known CLIs: {', '.join(plan.known_names)}")
        err.print(docs_pointer)
    return 2


def _operation_error(
    message: str,
    *,
    as_json: bool,
    err: Console,
    docs_urls: Sequence[str] = (),
) -> int:
    pointer = (
        "Canonical provider documentation is available with `sase agent-cli list -v`."
    )
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_AGENT_CLI_JSON_SCHEMA_VERSION,
                    "error": message,
                    "docs_urls": list(docs_urls),
                    "docs": pointer,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        err.print(Text(message, style="bold red"))
        for url in docs_urls:
            err.print(f"Docs: {url}")
        if not docs_urls:
            err.print(pointer)
    return 1


def _reason_with_docs(reason: str | None, docs_url: str | None) -> str | None:
    if not reason:
        return f"See {docs_url}" if docs_url else None
    if not docs_url or docs_url in reason:
        return reason
    return f"{reason}. See {docs_url}"


def _docs_urls(entries: Sequence[AgentCliUpdateEntry]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            entry.status.docs_url for entry in entries if entry.status.docs_url
        )
    )


def _version(value: str | None) -> str:
    return value or "unknown"


__all__ = [
    "UPDATE_AGENT_CLI_JSON_SCHEMA_VERSION",
    "handle_agent_cli_update_command",
]
