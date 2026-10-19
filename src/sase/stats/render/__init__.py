"""Shared Statistics render helpers used by the TUI, CLI, and Markdown."""

from sase.stats.render.card import render_project_card
from sase.stats.render.compose import render_project_stats
from sase.stats.render.context import RenderContext
from sase.stats.render.legend import render_coverage_footer, render_legend
from sase.stats.render.markdown import render_project_stats_markdown
from sase.stats.render.primitives import (
    format_compact,
    format_count,
    format_duration,
    format_relative_age,
    percent,
    share_bar,
    stacked_bar,
)
from sase.stats.render.tables import (
    render_model_table,
    render_patch_tree,
    render_project_table,
    render_repo_table,
)

__all__ = [
    "RenderContext",
    "format_compact",
    "format_count",
    "format_duration",
    "format_relative_age",
    "percent",
    "render_coverage_footer",
    "render_legend",
    "render_model_table",
    "render_patch_tree",
    "render_project_card",
    "render_project_stats",
    "render_project_stats_markdown",
    "render_project_table",
    "render_repo_table",
    "share_bar",
    "stacked_bar",
]
