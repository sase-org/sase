"""``sase agent hold`` — create, inspect, release, and wrap durable holds."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.core.agent_hold_facade import (
    AgentHoldArmResult,
    current_armer_wire,
    find_agent_hold,
    list_current_agent_holds,
    release_agent_hold,
    resolve_hold_ttl_seconds,
)
from sase.core.agent_hold_facade import (
    arm_agent_hold as _arm_agent_hold,
)
from sase.core.cli_duration import parse_cli_duration


def handle_agents_hold(args: argparse.Namespace) -> int:
    """Dispatch ``sase agent hold {create,list,release,run,show}``."""
    sub = getattr(args, "hold_subcommand", None) or "list"
    if sub == "create":
        return _handle_create(args)
    if sub == "list":
        return _handle_list(args)
    if sub == "release":
        return _handle_release(args)
    if sub == "run":
        return _handle_run(args)
    if sub == "show":
        return _handle_show(args)

    print("Usage: sase agent hold {create,list,release,run,show}", file=sys.stderr)
    return 1


def _selector_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "names": list(getattr(args, "names", None) or []),
        "tribes": list(getattr(args, "tribes", None) or []),
        "hoods": list(getattr(args, "hoods", None) or []),
        "future": bool(getattr(args, "future", False)),
        "pending": bool(getattr(args, "pending", False)),
    }


def _has_explicit_selector(selectors: Mapping[str, Any]) -> bool:
    return bool(
        selectors["names"]
        or selectors["tribes"]
        or selectors["hoods"]
        or selectors["future"]
        or selectors["pending"]
    )


def _resolve_ttl_seconds(raw: str | None, *, err: Console) -> float | None:
    requested: float | None = None
    if raw is not None:
        try:
            requested = parse_cli_duration(raw, flag="-T/--ttl")[0]
        except ValueError as exc:
            err.print(f"sase agent hold: {exc}", style="red", soft_wrap=True)
            return None
    try:
        return resolve_hold_ttl_seconds(requested)
    except ValueError as exc:
        err.print(f"sase agent hold: {exc}", style="red", soft_wrap=True)
        return None


def _handle_create(args: argparse.Namespace) -> int:
    err = Console(stderr=True)
    selectors = _selector_kwargs(args)
    if not _has_explicit_selector(selectors):
        err.print(
            "sase agent hold create: at least one of -n/-t/-H/-f/-p is required",
            style="red",
            soft_wrap=True,
        )
        return 2
    ttl_seconds = _resolve_ttl_seconds(getattr(args, "ttl", None), err=err)
    if ttl_seconds is None:
        return 2
    scope = getattr(args, "scope", None) or "project"
    try:
        result = _arm_agent_hold(scope=scope, ttl_seconds=ttl_seconds, **selectors)
    except Exception as exc:  # noqa: BLE001 - surfaced to the CLI, not swallowed.
        err.print(f"sase agent hold create: {exc}", style="red", soft_wrap=True)
        return 1
    _print_arm_result(result)
    return 0


def _handle_list(args: argparse.Namespace) -> int:
    err = Console(stderr=True)
    try:
        holds = list_current_agent_holds()
    except Exception as exc:  # noqa: BLE001 - surfaced to the CLI, not swallowed.
        err.print(f"sase agent hold list: {exc}", style="red", soft_wrap=True)
        return 1
    if getattr(args, "json", False):
        json.dump(holds, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    _print_holds_table(holds)
    return 0


def _handle_release(args: argparse.Namespace) -> int:
    err = Console(stderr=True)
    key = getattr(args, "key", None)
    try:
        if key is None:
            key = current_armer_wire()["key"]
        removed = release_agent_hold(key)
    except Exception as exc:  # noqa: BLE001 - surfaced to the CLI, not swallowed.
        err.print(f"sase agent hold release: {exc}", style="red", soft_wrap=True)
        return 1
    if not removed:
        err.print(
            f"sase agent hold release: no active hold for {key}",
            style="yellow",
            soft_wrap=True,
        )
        return 1
    print(f"Released hold {key}")
    return 0


def _handle_show(args: argparse.Namespace) -> int:
    err = Console(stderr=True)
    key: str = args.key
    try:
        hold = find_agent_hold(key)
    except Exception as exc:  # noqa: BLE001 - surfaced to the CLI, not swallowed.
        err.print(f"sase agent hold show: {exc}", style="red", soft_wrap=True)
        return 1
    if hold is None:
        err.print(
            f"sase agent hold show: no active hold for {key}",
            style="red",
            soft_wrap=True,
        )
        return 2
    if getattr(args, "json", False):
        json.dump(hold, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    _print_hold_detail(hold)
    return 0


def _handle_run(args: argparse.Namespace) -> int:
    err = Console(stderr=True)
    words = [
        str(part) for part in (getattr(args, "hold_run_command_words", None) or [])
    ]
    if words and words[0] == "--":
        words = words[1:]
    if not words:
        err.print(
            "sase agent hold run: provide a command after --",
            style="red",
            soft_wrap=True,
        )
        return 2

    selectors = _selector_kwargs(args)
    if not _has_explicit_selector(selectors):
        # The documented selector-free quiesce recipe: block everything
        # already waiting/queued plus everything launched from here on.
        selectors = {**selectors, "future": True, "pending": True}

    ttl_seconds = _resolve_ttl_seconds(getattr(args, "ttl", None), err=err)
    if ttl_seconds is None:
        return 2
    scope = getattr(args, "scope", None) or "project"

    try:
        # `run`'s own pid, not the parent shell's: this process stays alive
        # for exactly as long as COMMAND runs, so pid-liveness fail-open
        # reclaims the hold even if a SIGKILL skips the finally below.
        result = _arm_agent_hold(
            scope=scope,
            ttl_seconds=ttl_seconds,
            pid_override=os.getpid(),
            **selectors,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the CLI, not swallowed.
        err.print(f"sase agent hold run: {exc}", style="red", soft_wrap=True)
        return 1

    armer_key = result.record.get("armer", {}).get("key")
    _print_arm_result(result)
    try:
        return subprocess.run(words).returncode
    finally:
        if isinstance(armer_key, str):
            try:
                release_agent_hold(
                    armer_key,
                    reason="Released: `sase agent hold run` command exited",
                )
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup.
                err.print(
                    f"sase agent hold run: release failed for {armer_key}: {exc}",
                    style="yellow",
                    soft_wrap=True,
                )


def _print_arm_result(result: AgentHoldArmResult) -> None:
    console = Console()
    armer = result.record.get("armer", {})
    console.print(
        f"[green]Armed hold[/] {armer.get('key')} "
        f"(expires {_format_epoch_local(result.record.get('expires_at'))})"
    )
    if result.capture is not None:
        console.print(
            f"Captured {len(result.capture.artifact_dirs)} pending "
            f"({result.capture.waiting_count} waiting, "
            f"{result.capture.queued_count} queued); "
            f"skipped {result.capture.skipped_running_count} running"
        )


def _print_holds_table(holds: Sequence[Mapping[str, Any]]) -> None:
    console = Console()
    title = f"Agent Holds ({len(holds)})"
    if not holds:
        console.print(
            Panel(
                Text.from_markup("[dim]No active holds.[/dim]"),
                title=title,
                border_style="cyan",
            )
        )
        return

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ARMER", style="bold")
    table.add_column("KIND")
    table.add_column("SCOPE")
    table.add_column("SELECTORS")
    table.add_column("EXPIRES")

    for hold in holds:
        raw_armer = hold.get("armer")
        armer = raw_armer if isinstance(raw_armer, Mapping) else {}
        table.add_row(
            str(armer.get("key", "-")),
            str(armer.get("kind", "-")),
            _scope_label(hold.get("scope")),
            _selectors_label(hold.get("selectors")),
            _format_epoch_local(hold.get("expires_at")),
        )

    console.print(Panel(table, title=title, border_style="cyan"))


def _print_hold_detail(hold: Mapping[str, Any]) -> None:
    console = Console()
    raw_armer = hold.get("armer")
    armer: Mapping[str, Any] = raw_armer if isinstance(raw_armer, Mapping) else {}
    raw_selectors = hold.get("selectors")
    selectors: Mapping[str, Any] = (
        raw_selectors if isinstance(raw_selectors, Mapping) else {}
    )

    body = Text()
    for label, value in (
        ("Armer key", armer.get("key", "-")),
        ("Kind", armer.get("kind", "-")),
        ("Display", armer.get("display", "-")),
        ("Project", armer.get("project", "-")),
    ):
        body.append(f"{label}: ", style="bold")
        body.append(f"{value}\n")
    if armer.get("pid") is not None:
        body.append("Pid: ", style="bold")
        body.append(f"{armer.get('pid')}\n")
    if armer.get("done_marker_path"):
        body.append("Done marker: ", style="bold")
        body.append(f"{armer.get('done_marker_path')}\n")
    body.append("Scope: ", style="bold")
    body.append(f"{_scope_label(hold.get('scope'))}\n")
    body.append("Created: ", style="bold")
    body.append(f"{_format_epoch_local(hold.get('created_at'))}\n")
    body.append("Expires: ", style="bold")
    body.append(f"{_format_epoch_local(hold.get('expires_at'))}\n")

    body.append("\nSelectors:\n", style="bold")
    any_selector = False
    for key in ("names", "hoods", "tribes"):
        values = selectors.get(key) or []
        if values:
            any_selector = True
            body.append(f"  {key}: {', '.join(values)}\n")
    if selectors.get("future"):
        any_selector = True
        body.append("  future: true\n")
    artifact_dirs = selectors.get("artifact_dirs") or []
    if artifact_dirs:
        any_selector = True
        body.append(f"  pending: {len(artifact_dirs)} frozen artifact dir(s)\n")
    if not any_selector:
        body.append("  (none)\n")

    if artifact_dirs:
        body.append(
            f"\nFrozen pending artifact dirs ({len(artifact_dirs)}):\n", style="bold"
        )
        for artifact_dir in artifact_dirs:
            body.append(f"  {artifact_dir}\n")

    console.print(
        Panel(body, title=f"Hold: {armer.get('key', '-')}", border_style="cyan")
    )


def _scope_label(scope: Any) -> str:
    if isinstance(scope, Mapping):
        if scope.get("kind") == "project":
            return f"project:{scope.get('project', '?')}"
        if scope.get("kind") == "host":
            return "host"
    return "-"


def _selectors_label(selectors: Any) -> str:
    if not isinstance(selectors, Mapping):
        return "-"
    parts: list[str] = []
    for key in ("names", "hoods", "tribes"):
        values = selectors.get(key) or []
        if values:
            parts.append(f"{key}={','.join(values)}")
    if selectors.get("future"):
        parts.append("future")
    artifact_dirs = selectors.get("artifact_dirs") or []
    if artifact_dirs:
        parts.append(f"pending={len(artifact_dirs)}")
    return "; ".join(parts) if parts else "-"


def _format_epoch_local(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "unknown"
    from sase.core.time import get_timezone

    return datetime.fromtimestamp(float(value), tz=get_timezone()).isoformat(
        timespec="seconds"
    )
