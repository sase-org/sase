"""Rich panels and JSON envelope for ``sase agent drain``."""

from __future__ import annotations

from collections import defaultdict
import json
import time
from typing import Any

from rich import box
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.agent.provider_drain import (
    ProviderDrainError,
    ProviderDrainMove,
    ProviderDrainOutcome,
    ProviderDrainPlan,
    ProviderDrainSkip,
)
from sase.agent.restart import AgentRestartOutcome
from sase.agents.status_style import agent_status_text

AGENT_DRAIN_JSON_SCHEMA_VERSION = 1
_BORDER_STYLE = "#AF87FF"


def render_preview_panel(plan: ProviderDrainPlan) -> Panel:
    """Return the preview panel for a planned provider drain."""
    summary = Table(box=None, show_header=False, pad_edge=False, expand=True)
    summary.add_column("field", style="dim", no_wrap=True)
    summary.add_column("value", overflow="fold", ratio=1)
    summary.add_row("Disable", _disable_summary(plan))
    summary.add_row("Moves", Text(str(len(plan.moves)), style="bold green"))
    summary.add_row("Left alone", Text(str(len(plan.skips)), style="yellow"))
    if plan.model_override:
        summary.add_row("Model override", Text(plan.model_override))
    if plan.limit >= 0:
        summary.add_row("Limit", Text(str(plan.limit)))

    renderables: list[RenderableType] = [summary]
    if plan.moves:
        renderables.append(_moves_table(plan.moves))
    if plan.skips:
        renderables.append(_skips_table(plan.skips))

    return Panel(
        Group(*renderables),
        title=f"Drain · {plan.provider.upper()}",
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def render_receipt_panel(
    plan: ProviderDrainPlan,
    outcome: ProviderDrainOutcome,
) -> Panel:
    """Return the post-drain receipt panel."""
    failed = outcome.failed
    left_alone = len(plan.skips)
    summary = Text()
    summary.append(str(outcome.relaunched), style="bold green")
    summary.append(" relaunched · ", style="dim")
    summary.append(str(left_alone), style="bold yellow")
    summary.append(" left alone · ", style="dim")
    summary.append(str(failed), style="bold red" if failed else "bold green")
    summary.append(" failed")

    renderables: list[RenderableType] = [summary]
    if outcome.results:
        renderables.append(_results_table(plan, outcome))
    recovery_dirs = [
        result.recovery_dir for result in outcome.results if result.recovery_dir
    ]
    if recovery_dirs:
        recovery = Text("Recovery directories\n", style="dim")
        for path in recovery_dirs:
            recovery.append(f"  {path}\n")
        renderables.append(recovery)

    return Panel(
        Group(*renderables),
        title=f"Drained · {plan.provider.upper()}",
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def print_step(console: Console, step: str, status: str, detail: str) -> None:
    """Print one execution ledger line."""
    if status == "ok":
        mark = Text("✓", style="green")
    elif status == "fail":
        mark = Text("✗", style="red")
    elif status == "warn":
        mark = Text("!", style="yellow")
    else:
        mark = Text("•", style="dim")
    line = Text("  ")
    line.append_text(mark)
    line.append(f" {step:<10}", style="bold")
    if detail:
        line.append(detail)
    console.print(line)


def print_json(payload: dict[str, Any]) -> None:
    """Write one JSON object to stdout."""
    print(json.dumps(payload, indent=2, sort_keys=True))


def print_planning_error(err: Console, error: ProviderDrainError) -> None:
    """Print a refusal before anything was changed."""
    err.print(Text(error.message, style="bold red"))
    if error.hint:
        err.print(Text(error.hint, style="dim"))


def envelope_from_error(
    *,
    provider: str,
    error: ProviderDrainError,
    dry_run: bool,
    limit: int,
    model_override: str | None,
) -> dict[str, Any]:
    """Return a JSON envelope for a refused drain plan."""
    return {
        "schema_version": AGENT_DRAIN_JSON_SCHEMA_VERSION,
        "ok": False,
        "dry_run": dry_run,
        "provider": provider,
        "disable": None,
        "model_override": model_override,
        "limit": limit,
        "counts": {
            "moves": 0,
            "relaunched": 0,
            "failed": 0,
            "skipped": 0,
        },
        "moves": [],
        "skips": [],
        "results": [],
        "error": {
            "reason": error.reason,
            "message": error.message,
            "hint": error.hint,
        },
    }


def envelope_from_plan(
    plan: ProviderDrainPlan,
    *,
    dry_run: bool,
    outcome: ProviderDrainOutcome | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return the stable JSON envelope for a planned or executed drain."""
    relaunched = 0 if outcome is None else outcome.relaunched
    failed = 0 if outcome is None else outcome.failed
    ok = error is None and failed == 0
    return {
        "schema_version": AGENT_DRAIN_JSON_SCHEMA_VERSION,
        "ok": ok,
        "dry_run": dry_run,
        "provider": plan.provider,
        "disable": _disable_json(plan),
        "model_override": plan.model_override,
        "limit": plan.limit,
        "counts": {
            "moves": len(plan.moves),
            "relaunched": relaunched,
            "failed": failed,
            "skipped": len(plan.skips),
        },
        "moves": [_move_json(move) for move in plan.moves],
        "skips": [_skip_json(skip) for skip in plan.skips],
        "results": []
        if outcome is None
        else [_result_json(result) for result in outcome.results],
        "error": error,
    }


def _disable_summary(plan: ProviderDrainPlan) -> Text:
    from sase.ace.tui.modals.models_panel_provider_state import remaining_label
    from sase.ace.tui.provider_disable_display import (
        provider_disable_provenance_label,
    )

    now = time.time()
    text = Text()
    text.append(remaining_label(plan.disable, now=now), style="bold")
    text.append(" · ", style="dim")
    text.append(provider_disable_provenance_label(plan.disable), style="dim")
    return text


def _moves_table(moves: tuple[ProviderDrainMove, ...]) -> Table:
    table = Table(title="Moves", box=None, pad_edge=False, expand=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Agent", style="bold", no_wrap=True)
    table.add_column("Project")
    table.add_column("Route", overflow="fold", ratio=1)
    for move in moves:
        table.add_row(
            agent_status_text(move.status),
            move.presented_name,
            move.restart_plan.preview.project_display or move.project,
            _route_text(move),
        )
    return table


def _skips_table(skips: tuple[ProviderDrainSkip, ...]) -> Table:
    grouped: dict[str, list[ProviderDrainSkip]] = defaultdict(list)
    for skip in skips:
        grouped[skip.reason].append(skip)
    table = Table(title="Left alone", box=None, pad_edge=False, expand=True)
    table.add_column("Reason", style="yellow", no_wrap=True)
    table.add_column("Count", justify="right", no_wrap=True)
    table.add_column("Agents", overflow="fold", ratio=1)
    table.add_column("Detail", style="dim", overflow="fold", ratio=1)
    for reason in sorted(grouped):
        rows = grouped[reason]
        table.add_row(
            reason.replace("_", " "),
            str(len(rows)),
            _agent_list(rows),
            rows[0].detail,
        )
    return table


def _results_table(plan: ProviderDrainPlan, outcome: ProviderDrainOutcome) -> Table:
    moves_by_name = {move.name: move for move in plan.moves}
    table = Table(title="Results", box=None, pad_edge=False, expand=True)
    table.add_column("Agent", style="bold", no_wrap=True)
    table.add_column("Result", no_wrap=True)
    table.add_column("Route", overflow="fold", ratio=1)
    table.add_column("Recovery", overflow="fold", ratio=1)
    for result in outcome.results:
        move = moves_by_name.get(result.name)
        table.add_row(
            result.name,
            _result_status_text(result),
            _route_text(move) if move is not None else Text(""),
            Text(result.recovery_dir or "", style="dim"),
        )
    return table


def _route_text(move: ProviderDrainMove) -> Text:
    source_provider = move.restart_plan.preview.provider or "?"
    source_model = move.restart_plan.preview.model or "?"
    target_provider = move.route.target_provider or "?"
    target_model = move.route.target_model or "?"
    text = Text()
    text.append(f"{source_provider}/{source_model}", style="dim")
    text.append(" → ", style="bold")
    text.append(f"{target_provider}/{target_model}", style="green")
    return text


def _result_status_text(result: AgentRestartOutcome) -> Text:
    if result.status == "ok":
        return Text("relaunched", style="green")
    return Text(result.status.replace("_", " "), style="red")


def _agent_list(rows: list[ProviderDrainSkip]) -> str:
    return _truncated_names([row.presented_name for row in rows])


_SKIP_REASON_LABELS = {
    "monitor": "supervising a command",
    "pending_question": "waiting on a question",
    "caller": "the triggering agent itself",
    "capped": "dropped by --limit",
}


def usage_limit_drain_report_notes(payload: dict[str, Any] | None) -> list[str]:
    """Render the drain-outcome lines for the usage-limit disable notification.

    Works off the same stable JSON envelope ``envelope_from_plan``/
    ``envelope_from_error`` produce, so it reads the exact result a drain
    proc's ``sase agent drain --json`` run reported -- never a second,
    independently-computed summary.
    """
    if not payload:
        return ["Drain did not finish; see the drain proc log for details."]
    moves = payload.get("moves") or []
    skips = payload.get("skips") or []
    if not moves and not skips:
        return ["Drain found no agents on this provider to relaunch or leave alone."]
    lines: list[str] = []
    if moves:
        lines.append(_relaunched_line(moves, payload.get("results") or []))
    if skips:
        lines.append(_left_alone_line(skips))
    return lines


def _relaunched_line(moves: list[dict[str, Any]], results: list[dict[str, Any]]) -> str:
    moves_by_name = {move["name"]: move for move in moves}
    ok_names = [result["name"] for result in results if result.get("status") == "ok"]
    if not ok_names:
        return f"Relaunch attempted for {len(moves)} agent(s); none completed."
    providers: list[str] = []
    names: list[str] = []
    for name in ok_names:
        move = moves_by_name.get(name)
        if move is None:
            continue
        target = str((move.get("route") or {}).get("target_provider") or "?").upper()
        if target not in providers:
            providers.append(target)
        names.append(str(move.get("presented_name") or name))
    return (
        f"Relaunched {len(ok_names)} agent(s) on {_join_and(providers)}: "
        f"{_truncated_names(names)}"
    )


def _left_alone_line(skips: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for skip in skips:
        grouped[str(skip.get("reason") or "")].append(skip)
    parts = [
        f"{len(rows)} {_skip_reason_label(reason, rows[0])} "
        f"({_truncated_names([str(row.get('presented_name') or row.get('name')) for row in rows])})"
        for reason, rows in sorted(grouped.items())
    ]
    return "Left alone: " + ", ".join(parts)


def _skip_reason_label(reason: str, row: dict[str, Any]) -> str:
    if reason == "stranded":
        detail = str(row.get("detail") or "")
        return detail.split(";", 1)[0].strip() or "stranded"
    return _SKIP_REASON_LABELS.get(reason, reason.replace("_", " "))


def _join_and(items: list[str]) -> str:
    if not items:
        return "another provider"
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _truncated_names(names: list[str], *, limit: int = 5) -> str:
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f", +{len(names) - limit} more"


def _disable_json(plan: ProviderDrainPlan) -> dict[str, Any]:
    disable = plan.disable
    return {
        "provider": disable.provider,
        "mode": disable.mode,
        "source": disable.source,
        "created_at": disable.created_at,
        "expires_at": disable.expires_at,
    }


def _move_json(move: ProviderDrainMove) -> dict[str, Any]:
    return {
        "name": move.name,
        "presented_name": move.presented_name,
        "project": move.project,
        "project_display": move.restart_plan.preview.project_display,
        "status": move.status,
        "route": {
            "kind": move.route.kind,
            "target_provider": move.route.target_provider,
            "target_model": move.route.target_model,
        },
    }


def _skip_json(skip: ProviderDrainSkip) -> dict[str, Any]:
    return {
        "name": skip.name,
        "presented_name": skip.presented_name,
        "status": skip.status,
        "reason": skip.reason,
        "detail": skip.detail,
    }


def _result_json(result: AgentRestartOutcome) -> dict[str, Any]:
    stopped = {
        "action": result.stop_action,
        "pid": result.stop_result.pid,
        "status": result.stop_result.status,
        "artifacts_dir": result.stop_result.artifacts_dir,
    }
    launched = None
    if result.launched_pid is not None:
        launched = {
            "pid": result.launched_pid,
            "artifacts_dir": result.launched_artifacts_dir,
            "workspace_num": result.launched_workspace_num,
        }
    return {
        "name": result.name,
        "status": result.status,
        "stopped": stopped,
        "launched": launched,
        "recovery_dir": result.recovery_dir,
        "recovery_command": result.recovery_command,
        "renamed_to": result.renamed_to,
        "error": result.error,
    }
