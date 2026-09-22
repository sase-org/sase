"""Labeled launch-context cluster for each tab's status row (epic sase-14y, phase 2).

The launch default (model/effort) and the current project are global context,
not alerts, so they leave the crowded top bar and appear at the far right of
every tab's status row as one labeled cluster backed by the single
app-scoped :class:`LaunchContextSource`. Textual cannot share one widget
instance across three parents, so each tab mounts its own lightweight
:class:`LaunchContextBar` of render-only views; the source broadcasts to all
of them.

Visual grammar, left to right (``·`` separates the two groups)::

    Full:     model: opus@high · project: +sase
    Override: override opus@high 2h · project: +sase
    Compact:  opus@high · +sase
    No proj:  model: opus@high

On the Agents row only, a leading ``load: <load>/<capacity>`` gauge (an
Agents-row-only :class:`AgentLoadIndicator`) precedes this cluster.

``model:`` / ``project:`` are dim micro-labels naming the launch default and
the current project (never a sentence like "new agents ... in +sase": the
current project seeds filters and preselects the ``+`` picker row, it is not
silently applied to prompts). Chips render without their old top-bar pad
spaces; the labels supply the spacing instead. The ``· project: +sase`` group
collapses to zero width when no project resolves or the project indicator is
disabled. Density is chosen per host from the cells actually free on that row
by :func:`_choose_launch_context_density`.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.events import Resize
from textual.widgets import Static

from .agent_info_panel import AgentInfoPanel
from .agent_load_indicator import AgentLoadIndicator
from .artifacts.split_badge import ArtifactsSplitBadge
from .axe_info_panel import AxeInfoPanel
from .current_project_indicator import CurrentProjectIndicator
from .launch_context_source import LaunchContextSource, LaunchContextState
from .llm_override_indicator import LLMOverrideIndicator
from .panel_tab_strip import PanelTabStrip

LaunchContextDensity = Literal["full", "compact"]

_MODEL_LABEL_CALM = "model:"
_MODEL_LABEL_OVERRIDE = "override"
_PROJECT_LABEL = "project:"

_MODEL_LABEL_TOOLTIP_CALM = "The model new agents launch with by default."
_MODEL_LABEL_TOOLTIP_OVERRIDE = "A temporary override is replacing the launch default."
_PROJECT_LABEL_TOOLTIP = "The project you are currently working in."

# Cells of breathing room between a status row's own content and the cluster.
_MIN_GAP_CELLS = 2
# The Artifacts header's left spacer rests at the split-badge width so the
# sub-tab strip stays optically centered when no cluster is mounted.
_ARTIFACTS_BASE_SPACER_CELLS = 8

_STRIP_TIER_RANK = {"micro": 0, "compact": 1, "full": 2}


def _plain(widget: Static) -> str:
    """Return a bar child's rendered plain text.

    Every cluster child (labels, separator, both views) renders Rich
    ``Text``; the cast keeps mypy honest about ``Static.render``'s broad
    return type.
    """

    return cast(Text, widget.render()).plain


def _strip_tier_for_width(strip: PanelTabStrip, width: int) -> str:
    """Return the strip tier for *width* without disturbing rendered state.

    The strip's builders record click ranges and line width as a side effect,
    so the probe saves and restores them; pixels never change.
    """

    if width <= 0:
        return "micro"
    saved_ranges = strip._tab_ranges  # noqa: SLF001
    saved_width = strip._line_width  # noqa: SLF001
    try:
        return strip._reflow_tier_for_width(width)  # noqa: SLF001
    finally:
        strip._tab_ranges = saved_ranges  # noqa: SLF001
        strip._line_width = saved_width  # noqa: SLF001


def _strip_tier_width(strip: PanelTabStrip, tier: str) -> int:
    """Return the cell width of the strip rendered at *tier*, probe-only."""

    saved_ranges = strip._tab_ranges  # noqa: SLF001
    saved_width = strip._line_width  # noqa: SLF001
    try:
        content = strip._build_content(tier)  # type: ignore[arg-type]  # noqa: SLF001
        return cell_len(content.plain)
    finally:
        strip._tab_ranges = saved_ranges  # noqa: SLF001
        strip._line_width = saved_width  # noqa: SLF001


def _choose_launch_context_density(
    free_cells: int,
    *,
    full_cells: int,
    compact_cells: int,
) -> LaunchContextDensity:
    """Return the richest density that fits without truncating host content.

    ``full`` wins when it fits; otherwise ``compact`` renders even if it too
    overflows, letting the host's primary content clip on its right. The
    model chip is never hidden.
    """

    if free_cells >= full_cells:
        return "full"
    return "compact"


class LaunchContextBar(Horizontal):
    """Right-aligned launch-default + current-project cluster for a status row.

    Composes the model label, an :class:`LLMOverrideIndicator` view, the
    ``·`` separator, the project label, and a :class:`CurrentProjectIndicator`
    view. A render-only view over :class:`LaunchContextSource`: callers never
    touch the children directly, they drive the bar with
    :meth:`apply_launch_context` / :meth:`set_density`.
    """

    def __init__(
        self, *args: Any, density: LaunchContextDensity = "full", **kwargs: Any
    ) -> None:
        self._density: LaunchContextDensity = density
        self._chrome_cache: tuple[bool, bool, LaunchContextDensity] | None = None
        super().__init__(*args, **kwargs)

    @property
    def density(self) -> LaunchContextDensity:
        """Return the currently rendered density."""

        return self._density

    def compose(self) -> ComposeResult:
        """Yield the two labeled groups with the separator between them."""

        yield Static(f"{_MODEL_LABEL_CALM} ", id="launch-model-label")
        yield LLMOverrideIndicator(id="llm-override-indicator")
        yield Static(" · ", id="launch-separator")
        yield Static(f"{_PROJECT_LABEL} ", id="launch-project-label")
        yield CurrentProjectIndicator(id="current-project-indicator")

    def on_mount(self) -> None:
        """Paint labels/tooltips from the source state and fit the host row."""

        self.query_one(
            "#launch-model-label", Static
        ).tooltip = _MODEL_LABEL_TOOLTIP_CALM
        self.query_one("#launch-project-label", Static).tooltip = _PROJECT_LABEL_TOOLTIP
        try:
            source = self.app.query_one("#launch-context-source", LaunchContextSource)
        except Exception:  # noqa: BLE001 - unmounted bar degrades to defaults.
            return
        self.apply_launch_context(source.state)

    def apply_launch_context(self, state: LaunchContextState) -> None:
        """Forward source state to both views and re-sync labels and density."""

        try:
            model_view = self.query_one(LLMOverrideIndicator)
            project_view = self.query_one(CurrentProjectIndicator)
        except Exception:  # noqa: BLE001 - pre-compose broadcast is a no-op.
            return
        model_view.apply_launch_context(state)
        project_view.apply_launch_context(state)
        self._sync_chrome(state)
        self._request_host_fit()

    def set_density(self, density: LaunchContextDensity) -> bool:
        """Render *density*, returning True only when it actually changed."""

        if density == self._density:
            return False
        self._density = density
        self._apply_density()
        return True

    def refresh_density(self, free_cells: int) -> bool:
        """Choose the density for *free_cells* and render it when changed."""

        return self.set_density(
            _choose_launch_context_density(
                free_cells,
                full_cells=self.full_cells,
                compact_cells=self.compact_cells,
            )
        )

    @property
    def full_cells(self) -> int:
        """Return the cell width of the full cluster as currently resolved."""

        try:
            model_text = _plain(self.query_one(LLMOverrideIndicator))
            project_text = _plain(self.query_one(CurrentProjectIndicator))
            model_label = _plain(self.query_one("#launch-model-label", Static))
        except Exception:  # noqa: BLE001 - pre-mount probe degrades to zero.
            return 0
        width = cell_len(model_label) + cell_len(model_text)
        if project_text:
            width += (
                cell_len(" · ")
                + cell_len(f"{_PROJECT_LABEL} ")
                + cell_len(project_text)
            )
        return width

    @property
    def compact_cells(self) -> int:
        """Return the cell width of the compact cluster as currently resolved."""

        try:
            model_text = _plain(self.query_one(LLMOverrideIndicator))
            project_text = _plain(self.query_one(CurrentProjectIndicator))
        except Exception:  # noqa: BLE001 - pre-mount probe degrades to zero.
            return 0
        width = cell_len(model_text)
        if project_text:
            width += cell_len(" · ") + cell_len(project_text)
        return width

    @property
    def content_cells(self) -> int:
        """Return the cell width of the cluster at the current density."""

        if self._density == "compact":
            return self.compact_cells
        return self.full_cells

    def _sync_chrome(self, state: LaunchContextState) -> None:
        """Sync label text/styles and group visibility from source state."""

        try:
            model_label = self.query_one("#launch-model-label", Static)
            separator = self.query_one("#launch-separator", Static)
            project_label = self.query_one("#launch-project-label", Static)
            project_view = self.query_one(CurrentProjectIndicator)
        except Exception:  # noqa: BLE001 - pre-compose broadcast is a no-op.
            return
        override_active = state.override is not None
        project_empty = _plain(project_view) == ""
        chrome = (override_active, project_empty, self._density)
        if chrome == self._chrome_cache:
            return
        self._chrome_cache = chrome
        wanted_label = (
            f"{_MODEL_LABEL_OVERRIDE} " if override_active else f"{_MODEL_LABEL_CALM} "
        )
        if _plain(model_label) != wanted_label:
            model_label.update(wanted_label)
        model_label.set_class(override_active, "-override")
        model_label.tooltip = (
            _MODEL_LABEL_TOOLTIP_OVERRIDE
            if override_active
            else _MODEL_LABEL_TOOLTIP_CALM
        )
        separator.display = not project_empty
        project_label.display = (not project_empty) and self._density == "full"
        model_label.display = self._density == "full"

    def _apply_density(self) -> None:
        """Repaint label visibility for the current density and refit."""

        try:
            state = self.app.query_one(
                "#launch-context-source", LaunchContextSource
            ).state
        except Exception:  # noqa: BLE001 - unmounted bar keeps label state.
            return
        self._sync_chrome(state)

    def _request_host_fit(self) -> None:
        """Ask the hosting status row to recompute free cells and density."""

        node = self.parent
        while node is not None:
            fit = getattr(node, "fit_launch_context_bar", None)
            if callable(fit):
                fit()
                return
            node = node.parent


class AgentInfoRow(Horizontal):
    """Agents status row: the info panel plus the load gauge and cluster."""

    def on_resize(self, _event: Resize) -> None:
        """Refit the cluster density when the row gains or loses cells."""

        self.fit_launch_context_bar()

    def fit_launch_context_bar(self) -> None:
        """Pick the gauge and cluster density from the cells free beside the panel."""

        try:
            panel = self.query_one("#agent-info-panel", AgentInfoPanel)
            load = self.query_one("#agent-load-indicator", AgentLoadIndicator)
            bar = self.query_one(LaunchContextBar)
        except Exception:  # noqa: BLE001 - pre-compose fit is a no-op.
            return
        free = self.region.width - panel.content_width - 2 - _MIN_GAP_CELLS
        density = _choose_launch_context_density(
            max(0, free),
            full_cells=load.full_cells + bar.full_cells,
            compact_cells=load.compact_cells + bar.compact_cells,
        )
        bar.set_density(density)
        load.set_density(density)


class AxeInfoRow(Horizontal):
    """Services status row: the axe info panel plus the launch-context cluster."""

    def on_resize(self, _event: Resize) -> None:
        """Refit the cluster density when the row gains or loses cells."""

        self.fit_launch_context_bar()

    def fit_launch_context_bar(self) -> None:
        """Pick the cluster density from the cells free beside the panel."""

        try:
            panel = self.query_one("#axe-info-panel", AxeInfoPanel)
            bar = self.query_one(LaunchContextBar)
        except Exception:  # noqa: BLE001 - pre-compose fit is a no-op.
            return
        free = self.region.width - panel.content_width - 2 - _MIN_GAP_CELLS
        bar.refresh_density(max(0, free))


class ArtifactsHeader(Horizontal):
    """Artifacts status row: sub-tab strip, split badge, launch-context cluster.

    Keeps the sub-tab strip visually centered when the row has room by growing
    the left spacer to mirror the badge plus the cluster; otherwise the spacer
    rests at its base width and the strip centers in the remaining space.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._applied_spacer_width = _ARTIFACTS_BASE_SPACER_CELLS
        super().__init__(*args, **kwargs)

    def on_resize(self, _event: Resize) -> None:
        """Refit the cluster density when the header gains or loses cells."""

        self.fit_launch_context_bar()

    def fit_launch_context_bar(self) -> None:
        """Pick the cluster density and mirror the centering spacer.

        Density is measured against the strip tier that a compact cluster
        would leave room for, so the cluster never pushes the strip into a
        worse reflow than compact would — and a later strip reflow cannot
        strand the bar on a density poorer than what now fits.
        """

        try:
            strip = self.query_one("#artifacts-subtabs", PanelTabStrip)
            badge = self.query_one("#artifacts-split-badge", ArtifactsSplitBadge)
            spacer = self.query_one("#artifacts-split-spacer", Static)
            bar = self.query_one(LaunchContextBar)
        except Exception:  # noqa: BLE001 - pre-compose fit is a no-op.
            return
        header_width = max(0, self.region.width)
        badge_width = badge.region.width or _ARTIFACTS_BASE_SPACER_CELLS
        compact_cells = bar.compact_cells
        full_cells = bar.full_cells
        avail_compact = (
            header_width
            - _ARTIFACTS_BASE_SPACER_CELLS
            - badge_width
            - compact_cells
            - _MIN_GAP_CELLS
        )
        tier_compact = _strip_tier_for_width(strip, avail_compact)
        strip_width = _strip_tier_width(strip, tier_compact)
        free = (
            header_width
            - strip_width
            - badge_width
            - _ARTIFACTS_BASE_SPACER_CELLS
            - _MIN_GAP_CELLS
        )
        density: LaunchContextDensity = "compact"
        if free >= full_cells:
            mirror_full = badge_width + full_cells
            avail_full = (
                header_width - mirror_full - badge_width - full_cells - _MIN_GAP_CELLS
            )
            if (
                _STRIP_TIER_RANK[_strip_tier_for_width(strip, avail_full)]
                >= (_STRIP_TIER_RANK[tier_compact])
            ):
                density = "full"
        bar.set_density(density)
        mirror = badge_width + bar.content_cells
        needed = strip_width + badge_width + bar.content_cells + mirror + _MIN_GAP_CELLS
        wanted = mirror if header_width >= needed else _ARTIFACTS_BASE_SPACER_CELLS
        if wanted != self._applied_spacer_width:
            self._applied_spacer_width = wanted
            spacer.styles.width = wanted


__all__ = [
    "AgentInfoRow",
    "ArtifactsHeader",
    "AxeInfoRow",
    "LaunchContextBar",
    "LaunchContextDensity",
]
