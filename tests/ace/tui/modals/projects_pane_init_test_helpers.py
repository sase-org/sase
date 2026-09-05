"""Shared builders for Projects-tab init-flow tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.modals.projects_pane_init_payload import (
    InitActionRow,
    InitCheckPayload,
    InitPlannerRow,
    InitProjectPlan,
)

_PLANNED_AT = datetime(2026, 9, 4, 18, 17, 10)


def action_row(
    path: str = "sase/memory.md",
    *,
    operation: str = "update",
    detail: str = "",
    added: int = 0,
    removed: int = 0,
    diff_lines: tuple[str, ...] = (),
    diff_note: str | None = None,
    new_content: str | None = None,
    new_content_encoding: str | None = None,
) -> InitActionRow:
    return InitActionRow(
        path=path,
        operation=operation,
        detail=detail,
        added=added,
        removed=removed,
        diff_lines=diff_lines,
        diff_note=diff_note,
        new_content=new_content,
        new_content_encoding=new_content_encoding,
    )


def planner_row(
    name: str = "memory",
    *,
    label: str | None = None,
    summary: str = "Current",
    has_changes: bool = False,
    runnable: bool = True,
    requires_tty: bool = False,
    warnings: tuple[str, ...] = (),
    blockers: tuple[str, ...] = (),
    actions: tuple[InitActionRow, ...] = (),
    action_count: int | None = None,
    actions_truncated: bool = False,
) -> InitPlannerRow:
    return InitPlannerRow(
        name=name,
        label=label or name.title(),
        summary=summary,
        has_changes=has_changes,
        runnable=runnable,
        requires_tty=requires_tty,
        warnings=warnings,
        blockers=blockers,
        actions=actions,
        action_count=len(actions) if action_count is None else action_count,
        actions_truncated=actions_truncated,
    )


def current_planners() -> tuple[InitPlannerRow, ...]:
    return (
        planner_row("config", label="Config", summary="Current"),
        planner_row("memory", label="Memory", summary="Current"),
        planner_row("repo", label="Repos", summary="Current"),
        planner_row("skills", label="Skills", summary="Current"),
    )


def project_plan(
    name: str = "alpha",
    *,
    display_name: str | None = None,
    status: str = "current",
    unavailable_reason: str | None = None,
    error: str | None = None,
    planners: tuple[InitPlannerRow, ...] | None = None,
) -> InitProjectPlan:
    return InitProjectPlan(
        name=name,
        display_name=display_name or name,
        status=status,
        unavailable_reason=unavailable_reason,
        error=error,
        planners=current_planners() if planners is None else planners,
    )


def check_payload(
    *projects: InitProjectPlan,
    status: str = "drift",
    planned_at: datetime = _PLANNED_AT,
) -> InitCheckPayload:
    return InitCheckPayload(
        schema_version=1,
        status=status,  # type: ignore[arg-type]
        projects=projects,
        planned_at=planned_at,
    )


def single_update_payload() -> InitCheckPayload:
    """One drifted project with a memory update and a unified diff."""
    return check_payload(
        project_plan(
            "sase",
            display_name="sase",
            status="needs_attention",
            planners=(
                planner_row("config", label="Config", summary="Current"),
                planner_row(
                    "memory",
                    label="Memory",
                    summary="1 update",
                    has_changes=True,
                    actions=(
                        action_row(
                            "sase/task_types.json",
                            operation="update",
                            added=96,
                            removed=0,
                            diff_lines=(
                                "--- sase/task_types.json",
                                "+++ sase/task_types.json",
                                "@@ -1,0 +1,3 @@",
                                "+{",
                                '+  "bug": {},',
                                "+}",
                            ),
                        ),
                    ),
                ),
                planner_row("repo", label="Repos", summary="Current"),
                planner_row("skills", label="Skills", summary="Current"),
            ),
        )
    )


def mixed_all_payload() -> InitCheckPayload:
    """Canonical ``--all`` mix: drift, current, and unavailable."""
    return check_payload(
        project_plan(
            "alpha",
            status="needs_attention",
            planners=(
                planner_row(
                    "memory",
                    summary="1 update",
                    has_changes=True,
                    actions=(action_row(operation="update", added=1),),
                ),
            ),
        ),
        project_plan("beta"),
        project_plan("gamma"),
        project_plan(
            "gone",
            display_name="Gone",
            status="failed",
            unavailable_reason="primary workspace is unavailable: /gone",
            planners=(),
        ),
        status="blocked",
    )


def danger_payload() -> InitCheckPayload:
    """Overwrite action that trips the danger confirm variant."""
    return check_payload(
        project_plan(
            "sase",
            status="needs_attention",
            planners=(
                planner_row(
                    "memory",
                    summary="1 overwrite",
                    has_changes=True,
                    actions=(
                        action_row(
                            "AGENTS.md",
                            operation="overwrite",
                            added=2,
                            removed=2,
                        ),
                    ),
                ),
            ),
        )
    )


def tty_blocked_payload() -> InitCheckPayload:
    """TTY-held plan that offers the run-in-terminal valve."""
    return check_payload(
        project_plan(
            "sase",
            status="failed",
            planners=(
                planner_row(
                    "config",
                    summary="choose a machine identity",
                    has_changes=True,
                    runnable=False,
                    requires_tty=True,
                    blockers=["owner identity requires a TTY"],
                    actions=(action_row(operation="create"),),
                ),
            ),
        ),
        status="blocked",
    )


def raw_action(
    path: str = "sase/memory.md",
    *,
    operation: str = "update",
    detail: str = "",
    new_content: str | None = "# hi\n",
    new_content_encoding: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "path": path,
        "operation": operation,
        "detail": detail,
        "new_content": new_content,
    }
    if new_content_encoding is not None:
        row["new_content_encoding"] = new_content_encoding
    return row


def raw_planner(
    name: str = "memory",
    *,
    label: str | None = None,
    summary: str = "Current",
    has_changes: bool = False,
    runnable: bool = True,
    requires_tty: bool = False,
    warnings: list[str] | None = None,
    blockers: list[str] | None = None,
    actions: list[dict[str, Any]] | None = None,
    action_count: int | None = None,
    actions_truncated: bool | None = None,
) -> dict[str, Any]:
    action_rows = actions or []
    row: dict[str, Any] = {
        "name": name,
        "label": label or name.title(),
        "summary": summary,
        "has_changes": has_changes,
        "runnable": runnable,
        "requires_tty": requires_tty,
        "warnings": warnings or [],
        "blockers": blockers or [],
        "actions": action_rows,
        "action_count": len(action_rows) if action_count is None else action_count,
    }
    if actions_truncated:
        row["actions_truncated"] = True
    return row


def raw_project(
    name: str = "alpha",
    *,
    display_name: str | None = None,
    status: str = "current",
    unavailable_reason: str | None = None,
    error: str | None = None,
    planners: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": name,
        "display_name": display_name or name,
        "status": status,
        "unavailable_reason": unavailable_reason,
        "planners": planners
        if planners is not None
        else [
            raw_planner("config", label="Config"),
            raw_planner("memory", label="Memory"),
        ],
    }
    if error is not None:
        row["error"] = error
    return row


def raw_document(
    *projects: dict[str, Any],
    status: str = "current",
    schema_version: int = 1,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "status": status,
        "projects": list(projects),
    }
