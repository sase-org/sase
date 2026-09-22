"""Runner load gauge for the Agents status row.

Renders ``load: <load>/<capacity>`` at the right of the Agents row, just
before the launch-context cluster. The value run shares one color from the
usage-window palette in ``_usage_indicator_palette``, keyed on free-capacity
percent, so a given color means the same amount of headroom in both places.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import Static

from ._usage_indicator_palette import usage_percent_color, usage_zero_value_style

AgentLoadDensity = Literal["full", "compact"]

_LOAD_LABEL = "load: "
_TRAILING_SEPARATOR = " · "


def _format_load_value(value: object) -> str:
    """Format a runner load/capacity number, preferring integers.

    Non-numeric, ``bool``, or non-finite values render as ``—``. Other
    values round to 2 decimals: whole results render as integers, the rest
    trim trailing zeros. ``-0`` renders as ``0``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    number = float(value)
    if not math.isfinite(number):
        return "—"
    rounded = round(number, 2)
    if rounded == 0:
        rounded = 0.0
    if float(rounded).is_integer():
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _free_capacity_percent(limit: float, occupied: float) -> float:
    """Return free capacity percent for *limit*/*occupied*, de-noised."""
    free = max(0.0, limit - max(0.0, occupied))
    return round(free / limit * 100.0, 6)


def _agent_load_value_style(limit: float, occupied: float, *, dark: bool) -> str:
    """Return the value-run style for a known load/limit pair."""
    if round(occupied, 2) >= round(limit, 2):
        return usage_zero_value_style(dark=dark)
    return f"bold {usage_percent_color(_free_capacity_percent(limit, occupied), dark=dark)}"


def _build_agent_load_text(
    limit: float,
    occupied: float | None,
    *,
    dark: bool,
    density: AgentLoadDensity,
) -> Text:
    """Build the gauge text for *limit*/*occupied* at *density*."""
    text = Text()
    if limit <= 0:
        value_text = "—/—"
        value_style = "dim"
    elif occupied is None:
        value_text = f"—/{_format_load_value(limit)}"
        value_style = "dim"
    else:
        value_text = f"{_format_load_value(occupied)}/{_format_load_value(limit)}"
        value_style = _agent_load_value_style(limit, occupied, dark=dark)
    if density == "full":
        text.append(_LOAD_LABEL, style="dim")
    text.append(value_text, style=value_style)
    text.append(_TRAILING_SEPARATOR, style="dim")
    return text


def _agent_load_tooltip(limit: float, occupied: float | None) -> str:
    """Return the hover text for *limit*/*occupied*."""
    if limit <= 0:
        return "Runner capacity has not loaded yet."
    if occupied is None:
        return f"Runner load is unavailable; capacity is {_format_load_value(limit)} units."
    load_text = _format_load_value(occupied)
    limit_text = _format_load_value(limit)
    if round(occupied, 2) >= round(limit, 2):
        return (
            f"Runner load: {load_text} of {limit_text} capacity units in use "
            "(at capacity).\nNew agents queue until capacity frees up."
        )
    free_text = _format_load_value(max(0.0, limit - occupied))
    return (
        f"Runner load: {load_text} of {limit_text} capacity units in use "
        f"({free_text} free).\nNew agents queue when load reaches capacity."
    )


class AgentLoadIndicator(Static):
    """Right-side runner load gauge for the Agents status row.

    A render-only view: callers drive it with :meth:`update_load` and the
    hosting :class:`AgentInfoRow` drives density with :meth:`set_density`.
    """

    def __init__(
        self, *args: Any, density: AgentLoadDensity = "full", **kwargs: Any
    ) -> None:
        self._limit = 0.0
        self._occupied: float | None = None
        self._density: AgentLoadDensity = density
        super().__init__(
            _build_agent_load_text(0.0, None, dark=True, density=density),
            *args,
            **kwargs,
        )
        self.tooltip = _agent_load_tooltip(0.0, None)

    @property
    def density(self) -> AgentLoadDensity:
        """Return the currently rendered density."""

        return self._density

    @property
    def full_cells(self) -> int:
        """Return the cell width of the full gauge as currently resolved."""

        return cell_len(
            _build_agent_load_text(
                self._limit, self._occupied, dark=True, density="full"
            ).plain
        )

    @property
    def compact_cells(self) -> int:
        """Return the cell width of the compact gauge as currently resolved."""

        return cell_len(
            _build_agent_load_text(
                self._limit, self._occupied, dark=True, density="compact"
            ).plain
        )

    @property
    def content_cells(self) -> int:
        """Return the cell width of the gauge at the current density."""

        if self._density == "compact":
            return self.compact_cells
        return self.full_cells

    def update_load(self, limit: float, occupied: float | None) -> None:
        """Render *limit*/*occupied*, refitting the host row on width change.

        A no-op when nothing changed, so countdown ticks cost nothing.
        """

        if limit == self._limit and occupied == self._occupied:
            return
        old_width = self.content_cells
        self._limit = limit
        self._occupied = occupied
        self._apply_content()
        if self.content_cells != old_width:
            self._request_host_fit()

    def set_density(self, density: AgentLoadDensity) -> bool:
        """Render *density*, returning True only when it actually changed."""

        if density == self._density:
            return False
        self._density = density
        self._apply_content()
        return True

    def on_mount(self) -> None:
        """Watch the theme and paint the current load state."""

        self.watch(self.app, "theme", self._app_theme_changed, init=False)
        self._apply_content()

    def _app_theme_changed(self) -> None:
        """Repaint gauge colors after an app theme switch."""

        if self.is_mounted:
            self._apply_content()

    def _current_dark_theme(self) -> bool:
        """Return whether the active app theme is dark, defaulting to dark."""

        try:
            return bool(self.app.current_theme.dark)
        except Exception:
            return True

    def _apply_content(self) -> None:
        """Update content and tooltip from the cached load state."""

        try:
            dark = self._current_dark_theme()
        except Exception:
            dark = True
        content = _build_agent_load_text(
            self._limit, self._occupied, dark=dark, density=self._density
        )
        self.update(content)
        tooltip = _agent_load_tooltip(self._limit, self._occupied)
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    def _request_host_fit(self) -> None:
        """Ask the hosting status row to recompute free cells and density."""

        node = self.parent
        while node is not None:
            fit = getattr(node, "fit_launch_context_bar", None)
            if callable(fit):
                fit()
                return
            node = node.parent


__all__ = [
    "AgentLoadDensity",
    "AgentLoadIndicator",
]
