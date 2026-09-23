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
from .proc_indicator import MonitorIndicator, ProcIndicator
from .provider_disables_indicator import ProviderDisablesIndicator
from .stashed_prompts_indicator import StashedPromptsIndicator
from .tab_bar import TabBar
from .top_bar_group import (
    TOP_BAR_MIN_GAP,
    TOP_BAR_SEPARATOR,
    TopBarDensity,
    TopBarGroup,
    choose_top_bar_density,
    separator_visibility,
)
from .updates_indicator import UpdatesAvailableIndicator


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
        """Yield the seven groups with separators interleaved."""
        groups: tuple[TopBarGroup, ...] = (
            ProcIndicator(id="proc-indicator"),
            MonitorIndicator(id="monitor-indicator"),
            UpdatesAvailableIndicator(id="updates-indicator"),
            AliasOverridesIndicator(id="alias-overrides-indicator"),
            ProviderDisablesIndicator(id="provider-disables-indicator"),
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
        """Return the seven indicator groups in left-to-right order."""
        try:
            return [
                widget
                for widget in self.query(TopBarGroup)
                if isinstance(widget, TopBarGroup)
            ]
        except Exception:
            return []

    def separators(self) -> list[Static]:
        """Return the six separator widgets in left-to-right order."""
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
        ordered = self.groups()
        # Query order follows compose order for mounted children; fall back
        # to id order when the query backend reorders.
        by_id = {
            "proc-indicator": 0,
            "monitor-indicator": 1,
            "updates-indicator": 2,
            "alias-overrides-indicator": 3,
            "provider-disables-indicator": 4,
            "stashed-prompts-indicator": 5,
            "notification-indicator": 6,
        }
        ordered.sort(key=lambda g: by_id.get(str(g.id), 99))
        if len(ordered) != 7:
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
        ordered = self.groups()
        if not ordered:
            return 0
        by_id = {
            "proc-indicator": 0,
            "monitor-indicator": 1,
            "updates-indicator": 2,
            "alias-overrides-indicator": 3,
            "provider-disables-indicator": 4,
            "stashed-prompts-indicator": 5,
            "notification-indicator": 6,
        }
        ordered.sort(key=lambda g: by_id.get(str(g.id), 99))
        visible = [group.group_visible for group in ordered]
        width = sum(group.full_cells for group in ordered)
        width += sum(
            flags for flags in separator_visibility(tuple(visible))
        ) * cell_len(TOP_BAR_SEPARATOR)
        return width

    @property
    def compact_cells(self) -> int:
        """Return the cell width of the compact cluster as currently resolved."""
        ordered = self.groups()
        if not ordered:
            return 0
        by_id = {
            "proc-indicator": 0,
            "monitor-indicator": 1,
            "updates-indicator": 2,
            "alias-overrides-indicator": 3,
            "provider-disables-indicator": 4,
            "stashed-prompts-indicator": 5,
            "notification-indicator": 6,
        }
        ordered.sort(key=lambda g: by_id.get(str(g.id), 99))
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

    def fit_top_bar_indicators(self) -> None:
        """Pick the cluster density from the cells free beside the tabs."""
        try:
            tab_bar = self.query_one("#tab-bar", TabBar)
            cluster = self.query_one("#top-bar-indicators", TopBarIndicators)
        except Exception:
            return
        free = max(0, self.region.width - tab_bar.content_cells - TOP_BAR_MIN_GAP)
        cluster.set_density(
            choose_top_bar_density(free, full_cells=cluster.full_cells),
        )


__all__ = [
    "TopBar",
    "TopBarIndicators",
]
