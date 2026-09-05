"""Pure ``payload → RenderableType`` builders for :class:`InitPlanModal`."""

from __future__ import annotations

import shlex
from collections.abc import Sequence

from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.text import Text

from .projects_pane_init import InitScope
from .projects_pane_init_payload import (
    InitActionRow,
    InitCheckPayload,
    InitPlannerRow,
    InitProjectPlan,
)

_OPERATION_GLYPHS: dict[str, tuple[str, str]] = {
    "create": ("+", "green"),
    "update": ("~", "yellow"),
    "overwrite": ("~", "yellow"),
    "delete": ("−", "red"),
    "validate": ("●", "cyan"),
    "deploy": ("●", "cyan"),
}
_OPERATION_SEVERITY: dict[str, int] = {
    "delete": 0,
    "overwrite": 1,
    "update": 2,
    "create": 3,
    "deploy": 4,
    "validate": 5,
}
_WRITE_WARNING = (
    "This can write files and may commit, push, create repositories, "
    "or deploy managed files."
)
_MEMORY_WARNING = (
    "The memory step may commit and push generated project memory changes."
)
_ALL_SCOPE_NOTE = (
    "Scope is the canonical `sase init --all` inventory; marks, filter, "
    "and highlight are ignored."
)
_HELD_NOTE = "Held projects are left unchanged."
_TRUNCATED_NOTE = "… remaining actions omitted"
_TTY_SUFFIX = " (needs a terminal)"


def init_plan_title(scope: InitScope, payload: InitCheckPayload) -> str:
    """Return the border/button title without the ``(y)`` suffix."""
    if _is_single_project(scope):
        display = scope.display_names[0] if scope.display_names else scope.label
        return f"Initialize {display}"
    n = runnable_project_count(payload)
    noun = "project" if n == 1 else "projects"
    return f"Initialize {n} runnable {noun}"


def init_plan_confirm_label(scope: InitScope, payload: InitCheckPayload) -> str:
    """Return the primary button label."""
    if runnable_project_count(payload) == 0:
        return "Nothing runnable"
    return f"{init_plan_title(scope, payload)} (y)"


def runnable_project_count(payload: InitCheckPayload) -> int:
    """Count projects with at least one changed, runnable planner."""
    return sum(1 for project in payload.projects if project.changed_runnable)


def init_plan_is_danger(payload: InitCheckPayload) -> bool:
    """Whether any runnable planner has an overwrite or delete action."""
    for project in payload.projects:
        if not project.changed_runnable:
            continue
        for planner in project.planners:
            if not (planner.has_changes and planner.runnable):
                continue
            for action in planner.actions:
                if action.operation in {"overwrite", "delete"}:
                    return True
    return False


def init_plan_border_subtitle(*, show_diffs: bool, show_terminal: bool = False) -> str:
    """Return the modal border subtitle for the current diff-toggle state."""
    diff = "d hide diffs" if show_diffs else "d diff"
    terminal = " · t run in terminal" if show_terminal else ""
    return f"y run · {diff}{terminal} · esc cancel"


def init_plan_renderable(
    scope: InitScope,
    payload: InitCheckPayload,
    *,
    show_diffs: bool,
) -> RenderableType:
    """Build the scrollable preview body."""
    parts: list[RenderableType] = []
    if scope.all_projects or len(payload.projects) > 1:
        parts.append(_aggregate_line(payload))
        if scope.all_projects:
            parts.append(Text(_ALL_SCOPE_NOTE, style="dim"))
        parts.append(Text(""))
    parts.append(Text(_WRITE_WARNING, style="bold yellow"))
    if _memory_has_changes(payload):
        parts.append(Text(_MEMORY_WARNING, style="bold yellow"))
    if any(project.held for project in payload.projects):
        parts.append(Text(_HELD_NOTE, style="dim"))
    parts.append(Text(""))
    parts.append(Text("Would run", style="dim"))
    command = Text()
    command.append("$ ", style="dim")
    command.append(shlex.join(scope.apply_argv()), style="cyan")
    parts.append(command)
    parts.append(Text(""))
    attention, rest, current = _partition_projects(payload.projects)
    for index, project in enumerate((*attention, *rest)):
        if index:
            parts.append(Text(""))
        parts.extend(_project_section(project, show_diffs=show_diffs))
    if current:
        if attention or rest:
            parts.append(Text(""))
        parts.append(_current_summary(current))
    parts.append(Text(""))
    parts.append(_footer(payload))
    return Group(*parts)


def _is_single_project(scope: InitScope) -> bool:
    return not scope.all_projects and len(scope.project_names) == 1


def _memory_has_changes(payload: InitCheckPayload) -> bool:
    return any(
        planner.name == "memory" and planner.has_changes
        for project in payload.projects
        for planner in project.planners
    )


def _aggregate_line(payload: InitCheckPayload) -> Text:
    enabled = len(payload.projects)
    need_attention = sum(
        1 for project in payload.projects if project.changed_runnable or project.held
    )
    current = sum(1 for project in payload.projects if project.is_current)
    unavailable = sum(1 for project in payload.projects if project.unavailable)
    line = Text()
    line.append(f"{enabled} enabled", style="bold")
    line.append(" · ", style="dim")
    line.append(f"{need_attention} need attention")
    line.append(" · ", style="dim")
    line.append(f"{current} current", style="dim green")
    line.append(" · ", style="dim")
    line.append(f"{unavailable} unavailable", style="red" if unavailable else "dim")
    return line


def _partition_projects(
    projects: Sequence[InitProjectPlan],
) -> tuple[
    tuple[InitProjectPlan, ...],
    tuple[InitProjectPlan, ...],
    tuple[InitProjectPlan, ...],
]:
    attention: list[InitProjectPlan] = []
    rest: list[InitProjectPlan] = []
    current: list[InitProjectPlan] = []
    for project in projects:
        if project.is_current:
            current.append(project)
        elif project.held or project.changed_runnable:
            attention.append(project)
        else:
            rest.append(project)
    return tuple(attention), tuple(rest), tuple(current)


def _project_section(
    project: InitProjectPlan,
    *,
    show_diffs: bool,
) -> list[RenderableType]:
    parts: list[RenderableType] = [_project_rule(project)]
    if project.unavailable_reason:
        parts.append(Text(project.unavailable_reason, style="red"))
    if project.error:
        parts.append(Text(project.error, style="red"))
    for planner in project.planners:
        parts.append(_planner_row(planner))
        for action in planner.actions:
            parts.append(_action_row(action))
            if show_diffs:
                parts.extend(_diff_renderables(action))
        if planner.actions_truncated:
            parts.append(Text(f"    {_TRUNCATED_NOTE}", style="dim"))
        for warning in planner.warnings:
            parts.append(Text(f"    {warning}", style="yellow"))
        for blocker in planner.blockers:
            line = Text("    ")
            line.append(blocker, style="red")
            if planner.requires_tty:
                line.append(_TTY_SUFFIX, style="dim")
            parts.append(line)
    return parts


def _project_rule(project: InitProjectPlan) -> Rule:
    title = Text()
    title.append(project.display_name or project.name, style="bold cyan")
    if project.display_name and project.display_name != project.name:
        title.append(f" ({project.name})", style="dim")
    if project.status:
        title.append(f" · {project.status}", style="dim")
    return Rule(title, style="cyan")


def _planner_row(planner: InitPlannerRow) -> Text:
    line = Text()
    if planner.has_changes:
        glyph, style = _planner_glyph(planner)
    elif planner.blockers:
        glyph, style = ("●", "red")
    else:
        glyph, style = ("✓", "dim green")
    line.append(glyph, style=style)
    line.append(" ")
    line.append((planner.label or planner.name).upper(), style="bold")
    if planner.summary:
        line.append("  ")
        line.append(planner.summary)
    added = sum(action.added for action in planner.actions)
    removed = sum(action.removed for action in planner.actions)
    if planner.actions and (added or removed or planner.has_changes):
        line.append(f" · +{added} −{removed}", style="dim")
    return line


def _planner_glyph(planner: InitPlannerRow) -> tuple[str, str]:
    if not planner.actions:
        return "~", "yellow"
    ranked = min(
        planner.actions,
        key=lambda action: _OPERATION_SEVERITY.get(action.operation, 99),
    )
    return _OPERATION_GLYPHS.get(ranked.operation, ("~", "yellow"))


def _action_row(action: InitActionRow) -> Text:
    glyph, style = _OPERATION_GLYPHS.get(action.operation, ("~", "yellow"))
    line = Text("    ")
    line.append(glyph, style=style)
    line.append(" ")
    line.append(action.path or action.operation)
    if action.detail:
        line.append("  ")
        line.append(action.detail, style="dim")
    return line


def _diff_renderables(action: InitActionRow) -> list[RenderableType]:
    if action.diff_note and not action.diff_lines:
        return [Text(f"      {action.diff_note}", style="dim")]
    parts: list[RenderableType] = []
    for raw in action.diff_lines:
        line = Text("      ")
        if raw.startswith("+") and not raw.startswith("+++"):
            line.append(raw, style="green")
        elif raw.startswith("-") and not raw.startswith("---"):
            line.append(raw, style="red")
        elif raw.startswith("@@"):
            line.append(raw, style="dim")
        else:
            line.append(raw, style="dim")
        parts.append(line)
    if action.diff_note:
        parts.append(Text(f"      {action.diff_note}", style="dim"))
    return parts


def _current_summary(projects: Sequence[InitProjectPlan]) -> Text:
    names = ", ".join(project.display_name or project.name for project in projects)
    line = Text()
    line.append("✓", style="dim green")
    line.append(" Current  ", style="dim")
    line.append(names, style="dim")
    return line


def _footer(payload: InitCheckPayload) -> Text:
    stamp = payload.planned_at.strftime("%Y-%m-%d %H:%M")
    return Text(f"Planned {stamp} · confirm re-plans fresh", style="dim")


__all__ = [
    "init_plan_border_subtitle",
    "init_plan_confirm_label",
    "init_plan_is_danger",
    "init_plan_renderable",
    "init_plan_title",
    "runnable_project_count",
]
