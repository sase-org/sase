"""Labeled top-bar indicator cluster container and host row."""

from __future__ import annotations

from typing import Any

from rich.cells import cell_len
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.events import Resize
from textual.widgets import Static

from .alias_overrides_indicator import AliasOverridesIndicator
from .notification_indicator import NotificationIndicator
from .proc_indicator import ProcIndicator
from .stashed_prompts_indicator import StashedPromptsIndicator
from .tab_bar import TabBar
from .tools_indicator import ToolsIndicator
from .top_bar_group import (
    TOP_BAR_MIN_GAP,
    TOP_BAR_SEPARATOR,
    TopBarDensity,
    TopBarGroup,
    choose_top_bar_density,
    separator_visibility,
)
from .updates_indicator import UpdatesAvailableIndicator

_TOP_BAR_GROUP_IDS: tuple[str, ...] = (
    "tools-indicator",
    "proc-indicator",
    "updates-indicator",
    "alias-overrides-indicator",
    "stashed-prompts-indicator",
    "notification-indicator",
)


class TopBarIndicators(Horizontal):
    """Right-aligned labeled indicator cluster for the top bar."""

    def __init__(
        self, *args: Any, density: TopBarDensity = "full", **kwargs: Any
    ) -> None:
        self._density: TopBarDensity = density
        self._sync_cache: tuple[tuple[bool, ...], TopBarDensity] | None = None
        super().__init__(*args, **kwargs)

    @property
    def density(self) -> TopBarDensity:
        """Return the currently rendered density."""
        return self._density

    def compose(self) -> ComposeResult:
        """Yield the six groups with separators interleaved."""
        groups: tuple[TopBarGroup, ...] = (
            ToolsIndicator(id="tools-indicator"),
            ProcIndicator(id="proc-indicator"),
            UpdatesAvailableIndicator(id="updates-indicator"),
            AliasOverridesIndicator(id="alias-overrides-indicator"),
            StashedPromptsIndicator(id="stashed-prompts-indicator"),
            NotificationIndicator(id="notification-indicator"),
        )
        for index, group in enumerate(groups):
            if index:
                yield Static(TOP_BAR_SEPARATOR, classes="top-bar-separator")
            yield group

    def on_mount(self) -> None:
        """Sync separators once the cluster is mounted."""
        self.sync_top_bar_groups()

    def groups(self) -> list[TopBarGroup]:
        """Return the six indicator groups in left-to-right order."""
        try:
            return [
                widget
                for widget in self.query(TopBarGroup)
                if isinstance(widget, TopBarGroup)
            ]
        except Exception:
            return []

    def _ordered_groups(self) -> list[TopBarGroup]:
        """Return groups sorted into compose order."""
        ordered = self.groups()
        # Query order follows compose order for mounted children; fall back
        # to id order when the query backend reorders.
        by_id = {group_id: index for index, group_id in enumerate(_TOP_BAR_GROUP_IDS)}
        ordered.sort(key=lambda g: by_id.get(str(g.id), 99))
        return ordered

    def separators(self) -> list[Static]:
        """Return the five separator widgets in left-to-right order."""
        try:
            return [
                widget
                for widget in self.query(".top-bar-separator")
                if isinstance(widget, Static)
            ]
        except Exception:
            return []

    def sync_top_bar_groups(self) -> None:
        """Apply separator visibility and refit the host top bar."""
        ordered = self._ordered_groups()
        if len(ordered) != len(_TOP_BAR_GROUP_IDS):
            return
        visible = tuple(group.group_visible for group in ordered)
        cache = (visible, self._density)
        if cache == self._sync_cache:
            return
        self._sync_cache = cache
        flags = separator_visibility(visible)
        separators = self.separators()
        for separator, show in zip(separators, flags, strict=True):
            separator.display = show
        self._request_host_fit()

    @property
    def full_cells(self) -> int:
        """Return the cell width of the full cluster as currently resolved."""
        ordered = self._ordered_groups()
        if not ordered:
            return 0
        visible = [group.group_visible for group in ordered]
        width = sum(group.full_cells for group in ordered)
        width += sum(
            flags for flags in separator_visibility(tuple(visible))
        ) * cell_len(TOP_BAR_SEPARATOR)
        return width

    @property
    def compact_cells(self) -> int:
        """Return the cell width of the compact cluster as currently resolved."""
        ordered = self._ordered_groups()
        if not ordered:
            return 0
        visible = [group.group_visible for group in ordered]
        width = sum(group.compact_cells for group in ordered)
        width += sum(
            flags for flags in separator_visibility(tuple(visible))
        ) * cell_len(TOP_BAR_SEPARATOR)
        return width

    @property
    def content_cells(self) -> int:
        """Return the cell width at the current density."""
        if self._density == "compact":
            return self.compact_cells
        return self.full_cells

    def set_density(self, density: TopBarDensity) -> bool:
        """Render *density* on every group, returning True on any change."""
        changed = False
        if density != self._density:
            self._density = density
            changed = True
        for group in self.groups():
            if group.set_density(density):
                changed = True
        self.sync_top_bar_groups()
        return changed

    def _request_host_fit(self) -> None:
        """Ask the hosting top bar to recompute free cells and density."""
        node = self.parent
        while node is not None:
            fit = getattr(node, "fit_top_bar_indicators", None)
            if callable(fit):
                fit()
                return
            node = node.parent


class TopBar(Horizontal):
    """Top bar: tab strip plus the right-aligned indicator cluster."""

    def on_resize(self, _event: Resize) -> None:
        """Refit the cluster density when the bar gains or loses cells."""
        self.fit_top_bar_indicators()
        # A resize event can arrive with a stale or zero width before
        # layout settles. Re-read the widget size after the next refresh
        # so a pre-layout fit never sticks a compact density (dropped
        # group labels) onto a bar that fits full density once laid out.
        self.call_after_refresh(self._refit_from_current_size)

    def _refit_from_current_size(self) -> None:
        """Re-pick the cluster density from the laid-out bar width."""
        self.fit_top_bar_indicators()

    def fit_top_bar_indicators(self) -> None:
        """Pick the cluster density from the cells free beside the tabs."""
        try:
            tab_bar = self.query_one("#tab-bar", TabBar)
            cluster = self.query_one("#top-bar-indicators", TopBarIndicators)
            width = int(self.region.width)
        except Exception:
            return
        if width <= 0:
            # Pre-layout: the region has no width yet. Keep the current
            # (default full) density instead of sticking compact, which
            # no later fit would revisit when the size never changes.
            return
        free = max(0, width - tab_bar.content_cells - TOP_BAR_MIN_GAP)
        cluster.set_density(
            choose_top_bar_density(free, full_cells=cluster.full_cells),
        )


__all__ = [
    "TopBar",
    "TopBarIndicators",
]
