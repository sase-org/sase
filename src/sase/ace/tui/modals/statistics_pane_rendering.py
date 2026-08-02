"""Presentation helpers for the Admin Center Statistics pane."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from sase.ace.tui.keymaps import StatisticsPaneKeymaps, key_display_name
from sase.stats.ranges import PresetKey, StatsRange
from sase.telemetry.render import categorical_color, render_stat_tile

from .statistics_pane_data import (
    ProjectsGroupBy,
    StatisticsView,
    StatisticsViewData,
    XPromptsGroupBy,
    VIEW_DESCRIPTIONS,
    VIEW_LABELS,
    VIEW_ORDER,
    statistics_view_supports_grouping,
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
_XPROMPTS_GROUP_LABELS: dict[XPromptsGroupBy, str] = {
    "usage": "By Usage",
    "model": "By Model",
    "project": "By Project",
    "pairing": "Used With",
}


class StatisticsPanePresentationBase(StatisticsViewsRenderingMixin, Vertical):
    """Textual widget base responsible for painting statistics results."""

    _SCOPE_COMPACT_BELOW_WIDTH = 100
    _RUNNERS_STACK_BELOW_WIDTH = 108

    _keymaps: StatisticsPaneKeymaps
    _view: StatisticsView
    _projects_group_by: ProjectsGroupBy
    _xprompts_group_by: XPromptsGroupBy
    _project_filter: str | None
    _xprompt_focus: str | None
    _preset_key: PresetKey | None
    _range: StatsRange
    _loading: bool
    _last_result: StatisticsViewData | None
    _last_error: str
    _compact_scope: bool
    _runners_stacked: bool
    _pending_view_select: bool

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
        if self._view == "runners" and not result.views.runners.available:
            self._set_tiles_visible(False)
            self._update_static(
                "#statistics-body",
                self._runners_unavailable_renderable(result),
            )
            return
        if result.views.empty and self._view not in {"runners", "xprompts"}:
            self._set_tiles_visible(False)
            self._update_static(
                "#statistics-body",
                self._empty_state_renderable(result),
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
            self._error_state_renderable(message),
        )

    def _empty_state_renderable(self, result: StatisticsViewData) -> Panel:
        """Build recovery guidance for a range with no matching runs."""
        range_key = self._effective_key("cycle_range")
        recovery = Text()
        recovery.append(f"Press {range_key}", style=f"bold {_CYAN}")
        recovery.append(" to widen the range.")
        lines: list[Text] = [
            Text(
                f"No agent runs recorded in {result.selected_range.display_label}.",
                style="dim italic",
            ),
            recovery,
        ]
        if result.project_filter is not None:
            project_keys = self._effective_project_keys()
            project_label = result.project_display_snapshot.label_for(
                result.project_filter
            )
            clear_filter = Text()
            clear_filter.append(f"Press {project_keys}", style=f"bold {_GOLD}")
            clear_filter.append(f" to clear the {project_label} project filter.")
            lines.append(clear_filter)
        return Panel(
            Align.center(Group(*lines), vertical="middle"),
            title="Statistics",
            border_style="#444444",
            height=max(8, int(self.size.height or 24) - 11),
        )

    def _error_state_renderable(self, message: str) -> Panel:
        """Build first-load failure guidance using the effective refresh key."""
        refresh_key = self._effective_key("refresh")
        retry = Text()
        retry.append(f"Press {refresh_key}", style=f"bold {_ACCENT}")
        retry.append(" to retry.")
        return Panel(
            Align.center(
                Group(Text(message, style="red"), retry),
                vertical="middle",
            ),
            title="Statistics unavailable",
            border_style="red",
            height=max(8, int(self.size.height or 24) - 11),
        )

    def _runners_unavailable_renderable(self, result: StatisticsViewData) -> Panel:
        """Build guidance for an absent runner payload without hiding other views."""
        refresh_key = self._effective_key("refresh")
        range_key = self._effective_key("cycle_range")
        retry = Text()
        retry.append(f"Press {refresh_key}", style=f"bold {_ACCENT}")
        retry.append(" to retry, or ")
        retry.append(range_key, style=f"bold {_CYAN}")
        retry.append(" to choose another range.")
        lines: list[Text] = [
            Text(
                "No runner occupancy snapshot is available for "
                f"{result.selected_range.display_label}.",
                style="dim italic",
            ),
            Text(
                "The response may be older or partial, or All time may have no "
                "valid runner coverage.",
                style="dim",
            ),
            retry,
        ]
        if result.project_filter is not None:
            project_keys = self._effective_project_keys()
            project_label = result.project_display_snapshot.label_for(
                result.project_filter
            )
            clear_filter = Text()
            clear_filter.append(f"Press {project_keys}", style=f"bold {_GOLD}")
            clear_filter.append(f" to clear the {project_label} project filter.")
            lines.append(clear_filter)
        return Panel(
            Align.center(Group(*lines), vertical="middle"),
            title="Runners unavailable",
            border_style="#444444",
            height=max(8, int(self.size.height or 24) - 11),
        )

    def _heading_text(self) -> Text:
        heading = Text()
        heading.append("Statistics", style=f"bold {_ACCENT}")
        heading.append(" · ")
        heading.append(VIEW_LABELS[self._view], style="bold")
        return heading

    def _status_text(self) -> Text:
        status = Text(no_wrap=True, overflow="ellipsis")
        if self._loading:
            status.append("refreshing…", style="dim italic")
        elif self._last_error:
            status.append("load failed", style="red")
        elif self._last_result is not None:
            updated = (
                datetime.fromtimestamp(self._last_result.generated_at)
                .astimezone()
                .strftime("%H:%M:%S")
            )
            status.append(f"updated {updated}", style="dim")
        return status

    def _description_text(self) -> Text:
        return Text(
            f"› {VIEW_DESCRIPTIONS[self._view]}",
            style=f"dim {_ACCENT}",
            no_wrap=True,
            overflow="ellipsis",
        )

    @staticmethod
    def _scope_text(key: str, label: str, *, accent: str) -> Text:
        scope = Text(no_wrap=True, overflow="ellipsis")
        scope.append(f" {key} ", style=f"bold reverse {accent}")
        scope.append(f" {label} ", style="bold")
        return scope

    def _range_scope_text(self) -> Text:
        key = "/".join(
            (
                self._effective_key("cycle_range"),
                self._effective_key("cycle_range_reverse"),
            )
        )
        scope = self._scope_text(key, "Range", accent=_CYAN)
        if self._preset_key is None:
            scope.append("Custom", style=f"bold {_CYAN}")
            scope.append(" · ", style="dim")
        scope.append(self._range.display_label, style=f"bold {_CYAN}")
        if not self._compact_scope:
            scope.append(" · ", style="dim")
            scope.append(self._range.label, style=_CYAN)
        return scope

    def _group_scope_text(self) -> Text:
        key = self._effective_key("cycle_group")
        scope = self._scope_text(key, "Group", accent=_GREEN)
        if self._view == "projects":
            scope.append(
                f"Projects · {_PROJECTS_GROUP_LABELS[self._projects_group_by]}",
                style=f"bold {_GREEN}",
            )
        elif self._view == "xprompts":
            scope.append(
                f"XPrompts · {_XPROMPTS_GROUP_LABELS[self._xprompts_group_by]}",
                style=f"bold {_GREEN}",
            )
        else:
            scope.append("—", style="dim")
        return scope

    def _project_scope_text(self) -> Text:
        key = self._effective_project_keys()
        scope = self._scope_text(key, "Project", accent=_GOLD)
        if self._project_filter is None:
            scope.append("All projects", style=f"bold {_GOLD}")
            return scope

        project_label = self._project_filter
        if self._last_result is not None:
            project_label = self._last_result.project_display_snapshot.label_for(
                self._project_filter
            )
        scope.append("■ ", style=categorical_color(self._project_filter))
        scope.append(project_label, style=f"bold {_GOLD}")
        return scope

    def _xprompt_scope_text(self) -> Text:
        scope = self._scope_text(
            self._effective_xprompt_keys(),
            "XPrompt",
            accent=_ACCENT,
        )
        if self._xprompt_focus is None:
            scope.append("All xprompts", style=f"bold {_ACCENT}")
        else:
            scope.append("■ ", style=categorical_color(self._xprompt_focus))
            scope.append(f"#{self._xprompt_focus}", style=f"bold {_ACCENT}")
        return scope

    def _hints_text(self) -> Text:
        hints = Text(justify="center")
        if self._pending_view_select:
            hints.append(
                f"{self._effective_key('select_view')}… "
                f"press {self._view_selection_range_text()} to select a view",
                style=f"bold {_ACCENT}",
            )
            return hints
        hints.append(
            f"{self._effective_key('prev_view')} / "
            f"{self._effective_key('next_view')} · "
            f"{self._effective_key('select_view')}N",
            style=f"bold {_ACCENT}",
        )
        hints.append(" views")
        for action, description, color in (
            ("custom_range", "custom range", _CYAN),
            ("scroll_down", "scroll", _ACCENT),
            ("refresh", "refresh", _ACCENT),
            ("help", "help", _ACCENT),
        ):
            hints.append("   ")
            key = self._effective_key(action)
            if action == "scroll_down":
                key = self._effective_scroll_keys()
            hints.append(key, style=f"bold {color}")
            hints.append(f" {description}")
        if self._view == "xprompts":
            hints.append("   ")
            hints.append(
                self._effective_key("focus_xprompt"),
                style=f"bold {_ACCENT}",
            )
            hints.append(" focus")
        return hints

    @staticmethod
    def _view_selection_range_text() -> str:
        """Return the valid one-digit Statistics view selection range."""
        return f"1-{len(VIEW_ORDER)}"

    def _effective_scroll_keys(self) -> str:
        """Combine the effective half-page keys without wasting footer width."""
        down = self._effective_key("scroll_down")
        up = self._effective_key("scroll_up")
        prefix = "Ctrl+"
        if down.startswith(prefix) and up.startswith(prefix):
            return f"{down}/{up.removeprefix(prefix)}"
        return f"{down}/{up}"

    def _effective_project_keys(self) -> str:
        """Combine the configured forward and reverse project-filter keys."""
        return "/".join(
            (
                self._effective_key("cycle_project_filter"),
                self._effective_key("cycle_project_filter_reverse"),
            )
        )

    def _effective_xprompt_keys(self) -> str:
        """Combine the configured focus and clear-focus keys."""
        return "/".join(
            (
                self._effective_key("focus_xprompt"),
                self._effective_key("clear_xprompt_focus"),
            )
        )

    def _effective_key(self, action: str) -> str:
        """Return the configured display key for one Statistics action."""
        return key_display_name(getattr(self._keymaps, action))

    def _update_heading(self) -> None:
        self._update_static("#statistics-title", self._heading_text())
        self._update_static("#statistics-status", self._status_text())
        self._update_static("#statistics-description", self._description_text())
        self._update_scope()

    def _update_scope(self) -> None:
        self._update_static("#statistics-scope-range", self._range_scope_text())
        try:
            group_scope = self.query_one("#statistics-scope-group", Static)
            group_scope.set_class(
                not statistics_view_supports_grouping(self._view),
                "hidden",
            )
            group_scope.update(self._group_scope_text())
        except Exception:
            pass
        self._update_static("#statistics-scope-project", self._project_scope_text())
        try:
            xprompt_scope = self.query_one("#statistics-scope-xprompt", Static)
            xprompt_scope.set_class(self._view != "xprompts", "hidden")
            xprompt_scope.update(self._xprompt_scope_text())
        except Exception:
            pass

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
