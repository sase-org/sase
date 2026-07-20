"""Presentation helpers for the Admin Center Statistics pane."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.align import Align
from rich.panel import Panel
from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from sase.ace.tui.keymaps import StatisticsPaneKeymaps, statistics_help_bindings
from sase.stats.query import RuntimeGroupBy
from sase.stats.ranges import StatsRange
from sase.telemetry.render import render_stat_tile

from .statistics_pane_data import (
    ProjectsGroupBy,
    StatisticsView,
    StatisticsViewData,
    VIEW_LABELS,
)
from .statistics_pane_views import StatisticsViewsRenderingMixin

_ACCENT = "#FF87D7"
_CYAN = "#87D7FF"
_GOLD = "#FFD700"
_GREEN = "#5FD75F"
_PROJECTS_GROUP_LABELS: dict[ProjectsGroupBy, str] = {
    "project": "By Project",
    "changespec": "By ChangeSpec",
    "drilldown": "Project → ChangeSpec",
}


class StatisticsPanePresentationBase(StatisticsViewsRenderingMixin, Vertical):
    """Textual widget base responsible for painting statistics results."""

    _keymaps: StatisticsPaneKeymaps
    _view: StatisticsView
    _runtime_group_by: RuntimeGroupBy
    _projects_group_by: ProjectsGroupBy
    _project_filter: str | None
    _range: StatsRange
    _loading: bool
    _last_result: StatisticsViewData | None
    _last_error: str

    def _paint_loading(self) -> None:
        self._set_tiles_visible(self._view == "overview")
        if self._view == "overview":
            tile_width = self._tile_width()
            for index in range(5):
                self._update_static(
                    f"#statistics-tile-{index}",
                    self._loading_panel("Loading", width=tile_width, height=6),
                )
        self._update_static(
            "#statistics-body",
            self._loading_panel(
                "Loading statistics",
                width=max(48, int(self.size.width or 100) - 2),
                height=max(8, int(self.size.height or 24) - 12),
            ),
        )

    def _paint_current_view(self) -> None:
        result = self._last_result
        self._update_heading()
        self._set_tiles_visible(self._view == "overview")
        if result is None:
            self._paint_loading()
            return
        if result.views.empty:
            self._set_tiles_visible(False)
            self._update_static(
                "#statistics-body",
                Panel(
                    Align.center(
                        Text(
                            "No agent runs were recorded in the selected range.",
                            style="dim italic",
                        ),
                        vertical="middle",
                    ),
                    title="Statistics",
                    border_style="#444444",
                    height=max(8, int(self.size.height or 24) - 11),
                ),
            )
            return
        if self._view == "overview":
            self._paint_overview_tiles(result)
        self._update_static("#statistics-body", self._view_renderable(result))

    def _paint_overview_tiles(self, result: StatisticsViewData) -> None:
        overview = result.views.overview
        tile_width = self._tile_width()
        bucket_values = tuple(float(bucket.runs) for bucket in overview.buckets)
        delta = (
            overview.runs_delta_ratio * 100.0
            if overview.runs_delta_ratio is not None
            else None
        )
        tiles = (
            render_stat_tile(
                f"{overview.agents_run}\n✓ {overview.completed}  × {overview.failed}",
                caption="Agents Run",
                width=tile_width,
                height=6,
                key="agents",
                delta=delta,
                sparkline=bucket_values,
            ),
            render_stat_tile(
                overview.success_rate * 100.0,
                caption="Success Rate",
                width=tile_width,
                height=6,
                key="success",
                value_format="percent",
            ),
            render_stat_tile(
                f"{overview.commits}\n{overview.committing_agents} agents",
                caption="Commits",
                width=tile_width,
                height=6,
                key="commits",
            ),
            render_stat_tile(
                f"{overview.plans_proposed}\n{overview.epic_plans} epic · "
                f"{overview.tale_plans} tale",
                caption="Plans Proposed",
                width=tile_width,
                height=6,
                key="plans",
            ),
            render_stat_tile(
                f"{overview.questions}\n{overview.question_sessions} sessions",
                caption="Questions",
                width=tile_width,
                height=6,
                key="questions",
            ),
        )
        for index, renderable in enumerate(tiles):
            self._update_static(f"#statistics-tile-{index}", renderable)

    def _paint_error(self, message: str) -> None:
        self._last_error = message
        self._update_heading()
        if self._last_result is not None:
            return
        self._set_tiles_visible(False)
        self._update_static(
            "#statistics-body",
            Panel(
                Align.center(Text(message, style="red"), vertical="middle"),
                title="Statistics unavailable",
                border_style="red",
                height=max(8, int(self.size.height or 24) - 11),
            ),
        )

    def _heading_text(self) -> Text:
        heading = Text()
        heading.append("Statistics", style=f"bold {_ACCENT}")
        heading.append("  ·  ")
        view_label = VIEW_LABELS[self._view]
        if self._view == "runtime":
            view_label += f" by {self._runtime_group_by.title()}"
        elif self._view == "projects":
            view_label += f" · {_PROJECTS_GROUP_LABELS[self._projects_group_by]}"
        heading.append(view_label, style="bold")
        if self._project_filter is not None:
            heading.append(f"  ·  {self._project_filter}", style=f"bold {_GOLD}")
        if self._loading:
            heading.append("  ·  refreshing…", style="dim italic")
        elif self._last_error:
            heading.append("  ·  load failed", style="red")
        elif self._last_result is not None:
            updated = (
                datetime.fromtimestamp(self._last_result.generated_at)
                .astimezone()
                .strftime("%H:%M:%S")
            )
            heading.append(f"  ·  updated {updated}", style="dim")
        return heading

    def _range_text(self) -> Text:
        selected_range = Text(justify="center", no_wrap=True, overflow="ellipsis")
        selected_range.append("Range: ", style="bold")
        selected_range.append(self._range.display_label, style=f"bold {_CYAN}")
        selected_range.append("  ·  ", style="dim")
        selected_range.append(self._range.label, style=_CYAN)
        return selected_range

    def _hints_text(self) -> Text:
        bindings = statistics_help_bindings(self._keymaps)
        hints = Text(justify="center")
        if len(bindings) >= 2:
            hints.append(
                f"{bindings[0][0]} / {bindings[1][0]}", style=f"bold {_ACCENT}"
            )
            hints.append(" views")
        styles = (_CYAN, _GOLD, _GREEN, _ACCENT, _CYAN)
        for (key, description), color in zip(bindings[2:], styles, strict=False):
            if description == "Group By" and self._view == "runtime":
                description = f"Group: {self._runtime_group_by.title()}"
            elif description == "Group By" and self._view == "projects":
                description = (
                    f"Group: {_PROJECTS_GROUP_LABELS[self._projects_group_by]}"
                )
            hints.append("   ")
            hints.append(key, style=f"bold {color}")
            hints.append(f" {description.lower()}")
        return hints

    def _update_heading(self) -> None:
        self._update_static("#statistics-title", self._heading_text())
        self._update_static("#statistics-range", self._range_text())

    def _update_hints(self) -> None:
        self._update_static("#statistics-hints", self._hints_text())

    def _set_tiles_visible(self, visible: bool) -> None:
        try:
            self.query_one("#statistics-tiles", Horizontal).display = visible
        except Exception:
            pass

    def _update_static(self, selector: str, content: Any) -> None:
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass

    def _is_active_tab(self) -> bool:
        try:
            return getattr(self.screen, "_active_tab", None) == self.id
        except Exception:
            return False

    def _tile_width(self) -> int:
        width = max(60, int(self.size.width or 100))
        return max(12, (width - 4) // 5)

    @staticmethod
    def _loading_panel(
        label: str,
        *,
        width: int = 18,
        height: int = 6,
    ) -> Panel:
        return Panel(
            Align.center(Text(label, style="dim italic"), vertical="middle"),
            border_style="#444444",
            width=width,
            height=height,
            padding=0,
        )


__all__ = ["StatisticsPanePresentationBase"]
