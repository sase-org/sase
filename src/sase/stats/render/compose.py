"""Compose the shared Projects report from pure section renderers."""

from __future__ import annotations

from collections.abc import Callable

from rich.console import Group, RenderableType

from sase.stats.project.query import ProjectStatsGrouping
from sase.stats.project.view import ProjectStatsView
from sase.stats.registry import PROJECT_REPORT_GROUPINGS
from sase.stats.render.card import render_project_card
from sase.stats.render.context import RenderContext
from sase.stats.render.languages import render_language_table
from sase.stats.render.legend import render_coverage_footer, render_legend
from sase.stats.render.repos import render_repo_table
from sase.stats.render.tables import (
    render_model_table,
    render_patch_tree,
    render_project_table,
)

_GROUP_RENDERERS: dict[
    str, Callable[[ProjectStatsView, RenderContext], RenderableType]
] = {
    "project": render_project_table,
    "repo": render_repo_table,
    "language": render_language_table,
    "model": render_model_table,
    "patch": render_patch_tree,
}


def render_project_stats(
    view: ProjectStatsView,
    group_by: ProjectStatsGrouping | None,
    ctx: RenderContext,
) -> RenderableType:
    """Compose the card, selected grouping, coverage line, and legend."""
    grouping = group_by or view.effective_group_by
    if grouping not in PROJECT_REPORT_GROUPINGS:
        grouping = view.effective_group_by
    table = _GROUP_RENDERERS[grouping](view, ctx)
    return Group(
        render_project_card(view, ctx),
        table,
        render_coverage_footer(view, ctx),
        render_legend(view, ctx),
    )
