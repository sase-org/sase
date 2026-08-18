"""Rich panels, step ledger, and JSON envelope for ``sase agent restart``."""

from __future__ import annotations

import json
from typing import Any

from rich import box
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.agent.restart import (
    AgentRestartError,
    AgentRestartOutcome,
    AgentRestartPlan,
    AgentRestartPreview,
)
from sase.agents.status_style import agent_status_text
from sase.llm_provider.model_label import model_value_text

AGENT_RESTART_JSON_SCHEMA_VERSION = 1
_BORDER_STYLE = "#5FAFFF"


def render_preview_panel(plan: AgentRestartPlan) -> Panel:
    """Return the rounded preview panel for a planned restart."""
    preview = plan.preview
    table = Table(box=None, show_header=False, pad_edge=False, expand=True)
    table.add_column("field", style="dim", no_wrap=True)
    table.add_column("value", overflow="fold", ratio=1)

    rows: list[tuple[str, RenderableType]] = [
        ("Status", agent_status_text(preview.status)),
        ("Project", Text(preview.project_display)),
    ]
    if preview.patch:
        rows.append(("Patch", Text(preview.patch)))
    if preview.workspace_num is not None:
        rows.append(("Workspace", Text(f"#{preview.workspace_num}")))
    if preview.pid is not None:
        rows.append(("PID", Text(str(preview.pid))))
    model = _model_value(preview)
    if model is not None:
        rows.append(("Model", model))
    if preview.started:
        rows.append(("Started", Text(preview.started)))
    if preview.elapsed:
        rows.append(("Elapsed", Text(preview.elapsed)))
    if preview.family:
        rows.append(("Family", Text(preview.family)))
    if preview.bead:
        rows.append(("Bead", Text(preview.bead)))
    rows.append(("Prompt", Text(preview.prompt_excerpt)))
    rows.append(("Target", Text(preview.target)))
    rows.append(("Name reuse", Text(preview.name_reuse)))
    if preview.model_override_label:
        rows.append(("Model override", Text(preview.model_override_label)))

    for field, value in rows:
        table.add_row(field, value)
    return Panel(
        Group(table),
        title=f"Restart · {plan.presented_name}",
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def print_preview_warnings(console: Console, preview: AgentRestartPreview) -> None:
    """Print any applicable yellow warning lines below the preview panel."""
    for warning in preview.warnings:
        console.print(Text(warning, style="yellow"))


def print_step(console: Console, step: str, status: str, detail: str) -> None:
    """Print one ledger line as execution proceeds."""
    if status == "ok":
        mark = Text("✓", style="green")
    elif status == "fail":
        mark = Text("✗", style="red")
    else:
        mark = Text("•", style="dim")
    line = Text("  ")
    line.append_text(mark)
    line.append(f" {step:<10}", style="bold")
    if detail:
        line.append(detail)
    console.print(line)


def render_receipt_panel(plan: AgentRestartPlan, outcome: AgentRestartOutcome) -> Panel:
    """Return the post-launch receipt panel and next-step commands."""
    table = Table(box=None, show_header=False, pad_edge=False, expand=True)
    table.add_column("field", style="dim", no_wrap=True)
    table.add_column("value", overflow="fold", ratio=1)
    if outcome.launched_pid is not None:
        table.add_row("PID", Text(str(outcome.launched_pid)))
    if outcome.launched_workspace_num:
        table.add_row("Workspace", Text(f"#{outcome.launched_workspace_num}"))
    artifacts = outcome.launched_artifacts_dir or str(plan.artifacts_dir)
    table.add_row("Artifacts", Text(artifacts))
    next_block = Text(style="dim")
    next_block.append("\nNext\n")
    next_block.append(f"  sase agent show {plan.presented_name}\n")
    next_block.append(f"  tail -f {artifacts}/live_reply.md\n")
    next_block.append(f"  sase chat show {plan.presented_name}\n")
    return Panel(
        Group(table, next_block),
        title=f"Restarted · {plan.presented_name}",
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def envelope_from_plan(
    plan: AgentRestartPlan,
    *,
    dry_run: bool,
    outcome: AgentRestartOutcome | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return the stable JSON envelope for a planned or executed restart."""
    ok = error is None and (outcome is None or outcome.status == "ok")
    stopped: dict[str, Any] | None = None
    launched: dict[str, Any] | None = None
    if outcome is not None and not dry_run:
        stopped = {
            "action": outcome.stop_action,
            "pid": outcome.stop_result.pid,
            "status": outcome.stop_result.status,
            "artifacts_dir": outcome.stop_result.artifacts_dir
            or str(plan.artifacts_dir),
        }
        if outcome.launched_pid is not None:
            launched = {
                "pid": outcome.launched_pid,
                "artifacts_dir": outcome.launched_artifacts_dir,
                "workspace_num": outcome.launched_workspace_num,
            }
    return {
        "schema_version": AGENT_RESTART_JSON_SCHEMA_VERSION,
        "ok": ok,
        "dry_run": dry_run,
        "name": plan.name,
        "project": plan.project,
        "project_display": plan.preview.project_display,
        "prompt": {
            "source": "raw_xprompt.md",
            "vcs_tag": _json_vcs_tag(plan),
            "name_reuse": "forced",
            "model_override": plan.model_override,
        },
        "stopped": stopped,
        "launched": launched,
        "warnings": list(plan.preview.warnings),
        "error": error,
    }


def envelope_from_error(
    *,
    name: str,
    error: AgentRestartError,
    dry_run: bool,
) -> dict[str, Any]:
    """Return a failure envelope when planning itself was refused."""
    return {
        "schema_version": AGENT_RESTART_JSON_SCHEMA_VERSION,
        "ok": False,
        "dry_run": dry_run,
        "name": name,
        "project": None,
        "project_display": None,
        "prompt": None,
        "stopped": None,
        "launched": None,
        "warnings": [],
        "error": {"reason": error.reason, "message": error.message},
    }


def print_json(payload: dict[str, Any]) -> None:
    """Write one JSON object to stdout."""
    print(json.dumps(payload, indent=2, sort_keys=True))


def print_planning_error(
    err: Console,
    error: AgentRestartError,
    *,
    suggestions: list[str] | None = None,
) -> None:
    """Print a refusal: what was checked, what failed, and a next step."""
    err.print(Text(error.message, style="bold red"))
    if error.reason == "not_found":
        if suggestions:
            err.print(Text("Did you mean: " + ", ".join(suggestions), style="yellow"))
        err.print(Text("List agents with `sase agent list -a`.", style="dim"))
    elif error.hint:
        err.print(Text(error.hint, style="dim"))


def print_kill_failure(err: Console, outcome: AgentRestartOutcome) -> None:
    """Print a failed stop: nothing else was changed."""
    err.print(Text(outcome.error or outcome.stop_result.message, style="bold red"))
    err.print(Text("Nothing was changed.", style="yellow"))


def print_partial_failure(err: Console, outcome: AgentRestartOutcome) -> None:
    """Print a partial failure and the recovery command."""
    err.print(Text(outcome.error or "Relaunch failed.", style="bold red"))
    err.print(
        Text(
            "The old run was stopped and the name released.",
            style="yellow",
        )
    )
    if outcome.recovery_command:
        err.print(Text("Recover with:", style="dim"))
        err.print(Text(f"  {outcome.recovery_command}", style="bold"))


def _model_value(preview: AgentRestartPreview) -> Text | None:
    return model_value_text(
        preview.model,
        preview.provider,
        preview.reasoning_effort,
        preview.model_alias,
    )


def _json_vcs_tag(plan: AgentRestartPlan) -> str | None:
    from sase.xprompt import extract_vcs_workflow_tag, find_vcs_workflow_tag

    return extract_vcs_workflow_tag(plan.original_prompt) or find_vcs_workflow_tag(
        plan.original_prompt
    )
