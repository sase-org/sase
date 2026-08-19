"""Widget tree and inline range editor for the Admin Center Statistics pane."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Input, Static

from sase.ace.tui.widgets.panel_tab_strip import PanelTab, PanelTabStrip

from .statistics_pane_data import (
    VIEW_COMPACT_LABELS,
    VIEW_LABELS,
    VIEW_MICRO_LABELS,
    VIEW_ORDER,
    StatisticsView,
    statistics_view_supports_grouping,
)
from .statistics_pane_rendering import StatisticsPanePresentationBase

_ACCENT = "#FF87D7"
# Full eight-tab line is 119 cells; compact is 82. Keep a few cells of slack
# so 120- and 90-column Admin Center layouts never clip the strip.
_VIEWS_COMPACT_BELOW_WIDTH = 123
_VIEWS_MICRO_BELOW_WIDTH = 83
_VIEW_TABS: tuple[PanelTab, ...] = tuple(
    PanelTab(
        view,
        VIEW_LABELS[view],
        _ACCENT,
        compact_label=VIEW_COMPACT_LABELS[view],
        micro_label=VIEW_MICRO_LABELS[view],
    )
    for view in VIEW_ORDER
)
OVERVIEW_TILE_TARGETS: tuple[tuple[str, StatisticsView], ...] = (
    ("Agents Run", "projects"),
    ("Success Rate", "projects"),
    ("Commits", "projects"),
    ("Plans Proposed", "plans_questions"),
    ("Questions", "plans_questions"),
)


class _StatTile(Static):
    """Fixed-geometry summary tile. Overview assigns a click-through tooltip."""

    can_focus = False


class _CustomRangeInput(Input):
    """Transient inline range editor owned by the Statistics pane."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def action_cancel(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane._close_custom_range()

    def _pane(self) -> StatisticsPaneLayoutMixin | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, StatisticsPaneLayoutMixin):
                return node
            node = getattr(node, "parent", None)
        return None


class StatisticsPaneLayoutMixin(StatisticsPanePresentationBase):
    """Compose the Statistics widget tree and own its inline range editor."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="statistics-heading"):
            yield Static(self._heading_text(), id="statistics-title", markup=False)
            yield Static(self._status_text(), id="statistics-status", markup=False)
        yield PanelTabStrip(
            _VIEW_TABS,
            self._view,
            show_numbers=True,
            uppercase_active=True,
            compact_below=_VIEWS_COMPACT_BELOW_WIDTH,
            compact_separator="│",
            micro_below=_VIEWS_MICRO_BELOW_WIDTH,
            micro_separator="│",
            id="statistics-views",
        )
        yield Static(
            self._description_text(),
            id="statistics-description",
            markup=False,
        )
        with Horizontal(id="statistics-scope"):
            yield Static(
                self._range_scope_text(),
                id="statistics-scope-range",
                classes="statistics-scope-part",
                markup=False,
            )
            yield Static(
                self._group_scope_text(),
                id="statistics-scope-group",
                classes=(
                    "statistics-scope-part"
                    if statistics_view_supports_grouping(self._view)
                    else "statistics-scope-part hidden"
                ),
                markup=False,
            )
            yield Static(
                self._project_scope_text(),
                id="statistics-scope-project",
                classes="statistics-scope-part",
                markup=False,
            )
            yield Static(
                self._xprompt_scope_text(),
                id="statistics-scope-xprompt",
                classes=(
                    "statistics-scope-part"
                    if self._view == "xprompts"
                    else "statistics-scope-part hidden"
                ),
                markup=False,
            )
        yield _CustomRangeInput(
            placeholder=(
                "Custom range: 12h, 7d, 2w, YYYY-MM, "
                "YYYY-MM-DD..YYYY-MM-DD, or YYYY-MM-DD.."
            ),
            id="statistics-custom-range",
        )
        with Horizontal(id="statistics-tiles"):
            for index, (_caption, _target_view) in enumerate(OVERVIEW_TILE_TARGETS):
                yield _StatTile(
                    self._loading_panel("Loading", height=6),
                    id=f"statistics-tile-{index}",
                    classes="statistics-tile",
                )
        with VerticalScroll(id="statistics-body-scroll"):
            yield Static(
                self._loading_panel("Loading statistics", height=8),
                id="statistics-body",
            )
        yield Static(self._hints_text(), id="statistics-hints", markup=False)

    def _close_custom_range(self) -> None:
        try:
            self.query_one("#statistics-custom-range", Input).display = False
        except Exception:
            pass
        self.focus()


__all__ = ["OVERVIEW_TILE_TARGETS", "StatisticsPaneLayoutMixin"]
