"""Contextual, state-aware help for the Admin Center Statistics tab."""

from __future__ import annotations

from datetime import datetime

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.keymaps import StatisticsPaneKeymaps, statistics_help_bindings
from sase.ace.tui.keymaps.types import _STATISTICS_BINDING_META
from sase.stats.query import RuntimeGroupBy
from sase.stats.ranges import StatsRange

from .statistics_pane_data import (
    VIEW_DESCRIPTIONS,
    VIEW_LABELS,
    VIEW_ORDER,
    ProjectsGroupBy,
    StatisticsView,
)
from .statistics_pane_legends import VIEW_LEGENDS

_ACCENT = "#FF87D7"
_CYAN = "#87D7FF"
_GOLD = "#FFD700"
_GREEN = "#5FD75F"


class StatisticsHelpModal(ModalScreen[None]):
    """Explain Statistics views, controls, metrics, and data freshness."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("question_mark", "close", "Close"),
        ("j", "scroll_line_down", "Down"),
        ("k", "scroll_line_up", "Up"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
    ]

    def __init__(
        self,
        *,
        current_view: StatisticsView,
        selected_range: StatsRange,
        runtime_group_by: RuntimeGroupBy,
        projects_group_by: ProjectsGroupBy,
        project_label: str,
        generated_at: float | None,
        keymaps: StatisticsPaneKeymaps,
    ) -> None:
        super().__init__()
        self._current_view = current_view
        self._selected_range = selected_range
        self._runtime_group_by = runtime_group_by
        self._projects_group_by = projects_group_by
        self._project_label = project_label
        self._generated_at = generated_at
        self._keymaps = keymaps

    def compose(self) -> ComposeResult:
        with Container(id="statistics-help-container"):
            yield Static(self._title(), id="statistics-help-title")
            with VerticalScroll(id="statistics-help-scroll"):
                yield Static(self._content(), id="statistics-help-content")
            yield Static(
                "j/k scroll · Ctrl+D/U page · g/G top/bottom · ?/q/Esc close",
                id="statistics-help-footer",
            )

    def _title(self) -> Text:
        title = Text(justify="center")
        title.append("Statistics Help", style=f"bold {_ACCENT}")
        title.append(f"  ·  {VIEW_LABELS[self._current_view]}", style="bold")
        return title

    def _content(self) -> RenderableType:
        return Group(
            self._section("Views", self._views_text()),
            Text(""),
            self._section("Controls", self._controls_text()),
            Text(""),
            self._section("Metric glossary", self._glossary_text()),
            Text(""),
            self._section("Data & freshness", self._freshness_text()),
        )

    @staticmethod
    def _section(title: str, body: Text) -> Panel:
        return Panel(body, title=title, border_style=_ACCENT, padding=(0, 1))

    def _views_text(self) -> Text:
        text = Text()
        for index, view in enumerate(VIEW_ORDER):
            if index:
                text.append("\n")
            marker = "●" if view == self._current_view else "○"
            marker_style = f"bold {_ACCENT}" if view == self._current_view else "dim"
            text.append(f"{marker} ", style=marker_style)
            text.append(VIEW_LABELS[view], style="bold")
            text.append(f" — {VIEW_DESCRIPTIONS[view]}", style="dim")
        return text

    def _controls_text(self) -> Text:
        bindings = statistics_help_bindings(self._keymaps)
        text = Text()
        for index, ((action, description), (key, _)) in enumerate(
            zip(_STATISTICS_BINDING_META, bindings, strict=True)
        ):
            if index:
                text.append("\n")
            text.append(f" {key} ", style=f"bold reverse {_ACCENT}")
            text.append(f" {description}", style="bold")
            text.append(f" — {self._control_value(action)}", style="dim")
        return text

    def _control_value(self, action: str) -> str:
        if action in {"prev_view", "next_view"}:
            return f"current view: {VIEW_LABELS[self._current_view]}"
        if action == "cycle_range":
            return (
                f"{self._selected_range.display_label} · {self._selected_range.label}"
            )
        if action == "custom_range":
            return "enter a relative, calendar, or exact date range"
        if action == "cycle_group":
            current = "—"
            if self._current_view == "runtime":
                current = f"Runtime · {self._runtime_group_by.title()}"
            elif self._current_view == "projects":
                current = f"Projects · {self._projects_group_label()}"
            return f"{current}; available in Runtime and Projects"
        if action == "cycle_project_filter":
            return self._project_label
        if action == "refresh":
            return "reload now; auto-refreshes every 30 seconds while visible"
        if action == "help":
            return "this contextual guide"
        return ""

    def _projects_group_label(self) -> str:
        if self._projects_group_by == "project":
            return "By Project"
        if self._projects_group_by == "changespec":
            return "By ChangeSpec"
        return "Project → ChangeSpec"

    def _glossary_text(self) -> Text:
        text = Text()
        for view_index, view in enumerate(VIEW_ORDER):
            if view_index:
                text.append("\n")
            text.append(f"{VIEW_LABELS[view]}: ", style=f"bold {_CYAN}")
            for legend_index, legend in enumerate(VIEW_LEGENDS[view]):
                if legend_index:
                    text.append(" · ", style="dim")
                text.append(legend.term, style="bold")
                text.append(f" = {legend.meaning}", style="dim")
        return text

    def _freshness_text(self) -> Text:
        text = Text()
        text.append("Source", style="bold")
        text.append(
            " — durable agent-run records queried through the Rust statistics bindings.\n",
            style="dim",
        )
        text.append("Range", style=f"bold {_GOLD}")
        text.append(f" — {self._selected_range.label}.\n", style="dim")
        text.append("Refresh", style=f"bold {_GREEN}")
        text.append(
            " — automatically every 30 seconds while Statistics is visible; "
            "the refresh control reloads immediately.\n",
            style="dim",
        )
        text.append("Last loaded", style="bold")
        if self._generated_at is None:
            text.append(" — not yet loaded.", style="dim italic")
        else:
            loaded = (
                datetime.fromtimestamp(self._generated_at)
                .astimezone()
                .strftime("%Y-%m-%d %H:%M:%S %Z")
            )
            text.append(f" — {loaded}.", style="dim")
        return text

    def _scroll(self) -> VerticalScroll:
        return self.query_one("#statistics-help-scroll", VerticalScroll)

    def action_close(self) -> None:
        self.dismiss(None)

    def action_scroll_line_down(self) -> None:
        self._scroll().scroll_relative(y=1, animate=False)

    def action_scroll_line_up(self) -> None:
        self._scroll().scroll_relative(y=-1, animate=False)

    def action_scroll_down(self) -> None:
        scroll = self._scroll()
        scroll.scroll_relative(
            y=max(1, scroll.scrollable_content_region.height // 2),
            animate=False,
        )

    def action_scroll_up(self) -> None:
        scroll = self._scroll()
        scroll.scroll_relative(
            y=-max(1, scroll.scrollable_content_region.height // 2),
            animate=False,
        )

    def action_scroll_top(self) -> None:
        self._scroll().scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        self._scroll().scroll_end(animate=False)


__all__ = ["StatisticsHelpModal"]
