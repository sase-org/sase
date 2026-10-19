"""Projects-view renderers for the Admin Center Statistics pane."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sase.stats.loader import StatisticsViewData
from sase.stats.project.view import ProjectStatsView
from sase.stats.registry import PROJECTS_GROUP_ORDER, ProjectsGroupBy
from sase.stats.render.compose import render_project_stats
from sase.stats.render.context import RenderContext
from textual.widgets import Static

_DEFAULT_BODY_WIDTH = 48


class StatisticsProjectsRenderingMixin:
    """Render the shared Projects report without performing I/O."""

    _projects_group_by: ProjectsGroupBy
    _project_filter: str | None
    _last_result: StatisticsViewData | None
    size: Any

    if TYPE_CHECKING:

        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...

    def _single_project_scope(self) -> bool:
        """Return whether the painted Projects report has exactly one project."""
        if self._project_filter is not None:
            return True
        result = self._last_result
        if result is not None and result.project_stats is not None:
            return len(result.project_stats.projects) == 1
        return False

    def _effective_projects_group_by(self) -> ProjectsGroupBy:
        """Normalize grouping for one-project reports that still store project."""
        stored = self._projects_group_by
        if self._single_project_scope() and stored == "project":
            return "model"
        return stored

    def _projects_group_cycle_order(self) -> tuple[ProjectsGroupBy, ...]:
        """Return the ``g`` cycle, skipping project when only one project is in scope."""
        if self._single_project_scope():
            return tuple(
                grouping for grouping in PROJECTS_GROUP_ORDER if grouping != "project"
            )
        return PROJECTS_GROUP_ORDER

    def _projects_body_width(self) -> int:
        """Return the mounted ``#statistics-body`` width, with a size fallback."""
        try:
            width = int(self.query_one("#statistics-body", Static).size.width or 0)
        except Exception:
            width = 0
        if width > 0:
            return width
        return max(_DEFAULT_BODY_WIDTH, int(self.size.width or 100) - 2)

    def _project_render_context(self, report: ProjectStatsView) -> RenderContext:
        """Build an injectable context from the report and the actual body width."""
        timezone = ZoneInfo(report.timezone)
        now = datetime.fromisoformat(report.generated_at)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone)
        else:
            now = now.astimezone(timezone)
        return RenderContext(
            width=self._projects_body_width(),
            color=True,
            unicode=True,
            now=now,
            timezone=timezone,
            machine=report.machine,
        )

    def _projects_renderable(self, result: StatisticsViewData) -> Any:
        report = result.project_stats
        if report is None:
            from rich.text import Text

            return Text("Loading project statistics", style="dim italic")
        return render_project_stats(
            report,
            self._effective_projects_group_by(),
            self._project_render_context(report),
        )


__all__ = ["StatisticsProjectsRenderingMixin"]
