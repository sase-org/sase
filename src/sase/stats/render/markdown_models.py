"""Markdown model and patch tables for the shared Projects report."""

from __future__ import annotations

from collections.abc import Iterable

from sase.stats.project.models import ProjectStatsModel, ProjectStatsPatch
from sase.stats.project.view import ProjectStatsView
from sase.stats.render._markdown_shared import md_table
from sase.stats.render._text import (
    DASH,
    display_models,
    format_agent_time,
    group_models,
    maybe_int,
    relative_ts,
    sentinel_name,
    share_of,
)
from sase.stats.render._text import ModelGroup
from sase.stats.render.context import RenderContext
from sase.stats.render.primitives import format_count


def model_markdown(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
    headers = ["Model", "Commits", "Share", "Plans", "Epic", "Tale"]
    groups = group_models(display_models(view))
    total = sum(group.total.commits for group in groups)
    rows: list[list[str]] = []
    for group in groups:
        lead = group.models[0] if group.collapsed else group.total
        rows.append(_model_md_row(lead, group, ctx, total, indent=False))
        if group.collapsed:
            continue
        for row in group.visible_models:
            rows.append(_model_md_row(row, group, ctx, total, indent=True))
        if group.hidden_model_count:
            rows.append([f"+{group.hidden_model_count} more", "", "", "", "", ""])
    rows.append(
        [
            "total",
            format_count(total),
            "100%" if total else DASH,
            maybe_int(_sum_values(group.total.plans for group in groups)),
            maybe_int(_sum_values(group.total.plans_epic for group in groups)),
            maybe_int(_sum_values(group.total.plans_tale for group in groups)),
        ]
    )
    return ["## By model", ""] + md_table(headers, rows)


def _model_md_row(
    row: ProjectStatsModel,
    group: ModelGroup,
    _ctx: RenderContext,
    total: int,
    *,
    indent: bool,
) -> list[str]:
    if group.kind != "resolved":
        name = sentinel_name(group.kind)
    elif indent:
        name = f"  {row.model or DASH}"
    else:
        name = group.provider or "?"
        if group.collapsed and row.model:
            name = f"{name} · {row.model}"
        if row.model_is_alias:
            name += " (alias)"
    return [
        name,
        format_count(row.commits),
        share_of(row.commits, total or None),
        maybe_int(row.plans),
        maybe_int(row.plans_epic),
        maybe_int(row.plans_tale),
    ]


def patch_markdown(view: ProjectStatsView, ctx: RenderContext) -> list[str]:
    headers = [
        "Project → Patch",
        "Runs",
        "✓/×",
        "Run commits",
        "Agent time",
        "Last run",
    ]
    rows: list[list[str]] = []
    for project in view.projects:
        runs = project.runs
        rows.append(
            [
                project.label,
                maybe_int(None if runs is None else runs.runs),
                _ok_fail(
                    None if runs is None else runs.completed,
                    None if runs is None else runs.failed,
                ),
                DASH,
                format_agent_time(None if runs is None else runs.total_runtime_seconds),
                relative_ts(None if runs is None else runs.last_run_ts, ctx),
            ]
        )
        for patch in sorted(project.patches, key=lambda item: (-item.runs, item.name)):
            rows.append(_patch_md_row(patch, ctx))
        unattributed = 0 if runs is None else runs.unattributed_runs
        rows.append(["(no Patch)", format_count(unattributed), DASH, DASH, DASH, DASH])
    return ["## By patch", ""] + md_table(headers, rows)


def _patch_md_row(patch: ProjectStatsPatch, ctx: RenderContext) -> list[str]:
    name = f"  {patch.name}"
    if patch.has_pr:
        name += " (PR)"
    return [
        name,
        format_count(patch.runs),
        _ok_fail(patch.completed, patch.failed),
        format_count(patch.run_commits),
        format_agent_time(patch.total_runtime_seconds),
        relative_ts(patch.last_run_ts, ctx),
    ]


def _ok_fail(completed: int | None, failed: int | None) -> str:
    if completed is None and failed is None:
        return DASH
    return f"{format_count(completed or 0)}/{format_count(failed or 0)}"


def _sum_values(values: Iterable[int | None]) -> int | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


__all__ = [
    "model_markdown",
    "patch_markdown",
]
