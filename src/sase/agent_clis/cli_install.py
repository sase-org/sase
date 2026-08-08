"""Rich and JSON presentation for ``sase agent-cli install``."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .cli_update import command_text, render_reason
from .install import (
    AgentCliInstallEntry,
    AgentCliInstallPlan,
    AgentCliInstallsPlanned,
    execute_agent_cli_installs,
    plan_agent_cli_installs,
)
from .models import (
    AgentCliUnknownName,
    AgentCliUpdateResult,
    UpdateResultStatus,
    UpdateTrigger,
)

INSTALL_AGENT_CLI_JSON_SCHEMA_VERSION = 1

_RC_NOTICE = "SASE never edits your shell startup files."

PlanFn = Callable[..., AgentCliInstallPlan]
ExecuteFn = Callable[..., tuple[AgentCliUpdateResult, ...]]
ConfirmFn = Callable[[AgentCliInstallsPlanned, Console], bool]
IsTtyFn = Callable[[], bool]


def handle_agent_cli_install_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    plan_fn: PlanFn = plan_agent_cli_installs,
    execute_fn: ExecuteFn = execute_agent_cli_installs,
    confirm_fn: ConfirmFn | None = None,
    is_tty_fn: IsTtyFn | None = None,
) -> int:
    """Fetch, preview, confirm, and run provider-declared install scripts."""
    names = tuple(getattr(args, "names", ()) or ())
    as_json = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))
    force = bool(getattr(args, "force", False))
    offline = bool(getattr(args, "offline", False))
    refresh = bool(getattr(args, "refresh", False))
    assume_yes = bool(getattr(args, "yes", False))
    out = console or Console()
    err = err_console or Console(stderr=True)
    confirm = confirm_fn or _confirm_interactively
    is_tty = is_tty_fn or _stdin_is_tty

    if not names:
        return _usage_error(as_json=as_json, err=err)

    try:
        plan = plan_fn(
            names,
            force=force,
            refresh=refresh,
            offline=offline,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary must remain actionable.
        return _operation_error(
            f"Could not plan agent CLI installs: {exc}", as_json=as_json, err=err
        )

    if isinstance(plan, AgentCliUnknownName):
        return _unknown_name(plan, as_json=as_json, err=err)

    try:
        return _run_plan(
            plan,
            as_json=as_json,
            dry_run=dry_run,
            assume_yes=assume_yes,
            out=out,
            err=err,
            execute_fn=execute_fn,
            confirm=confirm,
            is_tty=is_tty,
        )
    finally:
        plan.cleanup()


def _run_plan(
    plan: AgentCliInstallsPlanned,
    *,
    as_json: bool,
    dry_run: bool,
    assume_yes: bool,
    out: Console,
    err: Console,
    execute_fn: ExecuteFn,
    confirm: ConfirmFn,
    is_tty: IsTtyFn,
) -> int:
    if dry_run:
        if as_json:
            print(json.dumps(_dry_run_json(plan), indent=2, sort_keys=True))
        else:
            _render_plan(plan.entries, console=out, dry_run=True)
        return 0

    if plan.runnable_entries and not assume_yes:
        if as_json or not is_tty():
            return _confirmation_required(plan, as_json=as_json, out=out, err=err)
        if not confirm(plan, out):
            err.print(Text("Aborted; no install script was executed.", style="yellow"))
            return 2

    try:
        results = execute_fn(plan, trigger=UpdateTrigger.CLI)
    except Exception as exc:  # noqa: BLE001 - preserve a stable CLI failure shape.
        return _operation_error(
            f"Could not execute agent CLI installs: {exc}", as_json=as_json, err=err
        )

    if as_json:
        print(json.dumps(_result_json(results), indent=2, sort_keys=True))
    else:
        _render_results(results, console=out)
    return (
        1
        if any(result.status is UpdateResultStatus.FAILED for result in results)
        else 0
    )


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _confirm_interactively(plan: AgentCliInstallsPlanned, out: Console) -> bool:
    _render_plan(plan.entries, console=out, dry_run=False)
    try:
        answer = out.input("Run the install script(s) above? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _confirmation_required(
    plan: AgentCliInstallsPlanned, *, as_json: bool, out: Console, err: Console
) -> int:
    message = (
        "Running a remote install script needs confirmation. Re-run with "
        "-y|--yes, or preview it first with -n|--dry-run."
    )
    if as_json:
        payload = _dry_run_json(plan)
        payload["error"] = message
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _render_plan(plan.entries, console=out, dry_run=False)
        err.print(Text(message, style="bold yellow"))
    return 2


def _dry_run_json(plan: AgentCliInstallsPlanned) -> dict[str, Any]:
    ready = len(plan.runnable_entries)
    return {
        "schema_version": INSTALL_AGENT_CLI_JSON_SCHEMA_VERSION,
        "dry_run": True,
        "shell_rc_notice": _RC_NOTICE,
        "counts": {
            "ready": ready,
            "skipped": len(plan.entries) - ready,
            "total": len(plan.entries),
        },
        "agent_clis": [_plan_entry_json(entry) for entry in plan.entries],
    }


def _plan_entry_json(entry: AgentCliInstallEntry) -> dict[str, Any]:
    status = entry.status
    script = entry.script
    return {
        "name": status.name,
        "display_name": status.display_name,
        "command": list(entry.argv) if entry.argv else None,
        "env": dict(entry.env_overlay),
        "install_script_url": status.install_script_url,
        "script_sha256": script.digest if script is not None else None,
        "script_bytes": script.size_bytes if script is not None else None,
        "install_dir": entry.install_dir,
        "installed_version": status.installed_version,
        "docs_url": status.docs_url,
        "reason": render_reason(entry.error or entry.skip_reason, status.docs_url),
        "error": entry.error,
        "ready": entry.ready,
    }


def _result_json(results: Sequence[AgentCliUpdateResult]) -> dict[str, Any]:
    counts = Counter(result.status.value for result in results)
    return {
        "schema_version": INSTALL_AGENT_CLI_JSON_SCHEMA_VERSION,
        "dry_run": False,
        "shell_rc_notice": _RC_NOTICE,
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
        "env": dict(result.env_overlay),
        "script_sha256": result.script_digest,
        "install_dir": result.install_dir,
        "install_dir_on_path": result.install_dir_on_path,
        "elapsed_seconds": round(result.elapsed, 3),
        "reason": render_reason(result.reason, result.docs_url),
        "output_tail": result.output_tail,
        "docs_url": result.docs_url,
    }


def _render_plan(
    entries: Sequence[AgentCliInstallEntry], *, console: Console, dry_run: bool
) -> None:
    body = Text()
    if not entries:
        body.append("No agent CLIs were selected.", style="yellow")
    for index, entry in enumerate(entries):
        if index:
            body.append("\n")
        status = entry.status
        if entry.script is not None and entry.argv is not None:
            body.append("● ", style="bold cyan")
            body.append(status.display_name, style="bold")
            body.append("\n  url:     ", style="dim")
            body.append(entry.script.url, style="cyan")
            body.append("\n  sha256:  ", style="dim")
            body.append(entry.script.digest, style="magenta")
            body.append(f"  ({entry.script.size_bytes} bytes)", style="dim")
            body.append("\n  command: ", style="dim")
            body.append(command_text(entry.argv, entry.env_overlay), style="cyan")
            if entry.install_dir:
                body.append("\n  target:  ", style="dim")
                body.append(entry.install_dir, style="cyan")
        else:
            body.append("○ ", style="yellow")
            body.append(status.display_name, style="bold")
            body.append(" — ")
            body.append(
                render_reason(entry.error or entry.skip_reason, status.docs_url)
                or "skipped",
                style="red" if entry.error else "yellow",
            )

    console.print(
        Panel(
            body,
            title="Agent CLI install preview",
            subtitle=(
                f"Dry run · nothing executed · {_RC_NOTICE}" if dry_run else _RC_NOTICE
            ),
            border_style="cyan",
        )
    )


def _render_results(
    results: Sequence[AgentCliUpdateResult], *, console: Console
) -> None:
    body = Text()
    if not results:
        body.append("No agent CLIs were selected.", style="yellow")
    for index, result in enumerate(results):
        if index:
            body.append("\n")
        glyph, style, label = {
            UpdateResultStatus.UPDATED: ("✓", "green", "installed"),
            UpdateResultStatus.ALREADY_CURRENT: ("✓", "cyan", "already installed"),
            UpdateResultStatus.FAILED: ("✗", "bold red", "failed"),
            UpdateResultStatus.SKIPPED: ("○", "yellow", "skipped"),
        }[result.status]
        body.append(f"{glyph} ", style=style)
        body.append(result.display_name, style="bold")
        body.append(f" — {label}", style=style)
        if result.new_version and result.status is UpdateResultStatus.UPDATED:
            body.append(f" ({result.new_version})", style="green")
        if result.install_dir and result.status is UpdateResultStatus.UPDATED:
            body.append("\n  location: ", style="dim")
            body.append(result.install_dir, style="cyan")
            body.append(
                " (on PATH)" if result.install_dir_on_path else " (not on PATH)",
                style="green" if result.install_dir_on_path else "yellow",
            )
        if result.script_digest:
            body.append("\n  sha256:   ", style="dim")
            body.append(result.script_digest, style="magenta")
        reason = render_reason(result.reason, result.docs_url)
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
            (UpdateResultStatus.UPDATED, "installed"),
            (UpdateResultStatus.SKIPPED, "skipped"),
            (UpdateResultStatus.FAILED, "failed"),
        )
        if counts[status.value]
    )
    console.print(
        Panel(
            body,
            title="Agent CLI installs",
            subtitle=f"{subtitle or 'No changes'} · {_RC_NOTICE}",
            border_style="red" if counts[UpdateResultStatus.FAILED.value] else "green",
        )
    )


def _usage_error(*, as_json: bool, err: Console) -> int:
    message = (
        "Specify one or more agent CLIs to install, for example "
        "`sase agent-cli install muse`."
    )
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": INSTALL_AGENT_CLI_JSON_SCHEMA_VERSION,
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
                    "schema_version": INSTALL_AGENT_CLI_JSON_SCHEMA_VERSION,
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


def _operation_error(message: str, *, as_json: bool, err: Console) -> int:
    pointer = (
        "Canonical provider documentation is available with `sase agent-cli list -v`."
    )
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": INSTALL_AGENT_CLI_JSON_SCHEMA_VERSION,
                    "error": message,
                    "docs": pointer,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        err.print(Text(message, style="bold red"))
        err.print(pointer)
    return 1


__all__ = [
    "INSTALL_AGENT_CLI_JSON_SCHEMA_VERSION",
    "handle_agent_cli_install_command",
]
