"""Widget tree and inline range editor for the Admin Center Statistics pane."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.events import Resize
from textual.widgets import Input, Static

from sase.ace.tui.widgets.panel_tab_strip import PanelTab, PanelTabStrip

from .statistics_pane_data import (
    STATISTICS_VIEW_BY_ID,
    STATISTICS_VIEW_SPECS,
    StatisticsView,
    StatisticsViewSpec,
    statistics_view_description_text,
    statistics_view_supports_grouping,
)
from .statistics_pane_rendering import StatisticsPanePresentationBase

_ACCENT = "#FF87D7"
# Full eight-tab line is 130 cells with 01-style shortcuts; compact is 90.
# Use compact at 120 columns and keep the 90-column layout unclipped.
_VIEWS_COMPACT_BELOW_WIDTH = 131
_VIEWS_MICRO_BELOW_WIDTH = 90
_VIEW_TABS: tuple[PanelTab, ...] = tuple(
    PanelTab(
        spec.id,
        spec.label,
        _ACCENT,
        compact_label=spec.compact_label,
        micro_label=spec.micro_label,
        shortcut=f"{index:02d}",
    )
    for index, spec in enumerate(STATISTICS_VIEW_SPECS, start=1)
)
OVERVIEW_TILE_TARGETS: tuple[tuple[str, StatisticsView], ...] = (
    ("Agents Run", "projects"),
    ("Success Rate", "projects"),
    ("Commits", "projects"),
    ("Plans Proposed", "plans_questions"),
    ("Questions", "plans_questions"),
)


class _StatisticsDescription(Static):
    """One-row, width-aware caption for the active Statistics view."""

    can_focus = False

    def __init__(self, spec: StatisticsViewSpec, **kwargs: Any) -> None:
        self._spec = spec
        self._variant = "full"
        super().__init__(
            statistics_view_description_text(spec, width=0),
            markup=False,
            **kwargs,
        )
        self.styles.width = "100%"

    def set_spec(self, spec: StatisticsViewSpec) -> None:
        """Swap the active view copy and repaint when the caption changes."""
        changed = spec != self._spec
        self._spec = spec
        self._apply_width(int(self.size.width), force=changed)

    def on_resize(self, event: Resize) -> None:
        """Repaint only when the full/compact variant actually changes."""
        self._apply_width(int(event.size.width), force=False)

    def _apply_width(self, width: int, *, force: bool) -> None:
        text = statistics_view_description_text(self._spec, width=width)
        variant = "full" if text.plain == f"› {self._spec.description}" else "compact"
        if not force and variant == self._variant:
            return
        self._variant = variant
        self.update(text)


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
        yield _StatisticsDescription(
            STATISTICS_VIEW_BY_ID[self._view],
            id="statistics-description",
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

    def _update_heading(self) -> None:
        super()._update_heading()
        self._update_rail()

    def _update_rail(self) -> None:
        """Keep the description rail on the mounted ``_view`` catalog row."""
        try:
            self.query_one(
                "#statistics-description",
                _StatisticsDescription,
            ).set_spec(STATISTICS_VIEW_BY_ID[self._view])
        except Exception:
            pass

    def _close_custom_range(self) -> None:
        try:
            self.query_one("#statistics-custom-range", Input).display = False
        except Exception:
            pass
        self.focus()


__all__ = ["OVERVIEW_TILE_TARGETS", "StatisticsPaneLayoutMixin"]
