"""Tools indicator widget for sase's TUI (epic sase-1ih, phase top-bar-tools-bg)."""

from typing import Any

from rich.text import Text

from sase.ace.tui.proc_gear_chips import MONITOR_GEAR_HUE, gear_chip
from sase.ace.tui.tool_runs.top_bar import TopBarToolsModel
from sase.tool.view_vocabulary import TOOL_RUN_ACCENT, TOOL_RUN_GLYPH

from .top_bar_group import TopBarGroup, icon_count_chip

#: Red for the silent-run chip (shared with the row-chip vocabulary).
_SILENT_HUE = "#FF5F5F"


class ToolsIndicator(TopBarGroup):
    """Shows live ToolRun executions in the top bar.

    Renders as ``tools: ⚒ N`` for healthy live runs, then ``⚒⚠ M`` for
    silent ones, then the orange gear for bare monitors (monitor turns
    not carrying a run). Each chip hides at zero and the group hides only
    when all chips are zero. Clicking opens Admin Center › Tools › Runs
    with all projects.
    """

    GROUP_LABEL = "tools"
    CLICK_ACTION = "open_live_tool_runs"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._model = TopBarToolsModel()
        self._set_body(self._build_content(self._model))
        self.tooltip = self._model.tooltip

    def set_model(self, model: TopBarToolsModel) -> None:
        """Update the displayed tools model; a no-op when nothing changed."""
        if self._model == model:
            return
        self._model = model
        self._set_body(self._build_content(model))
        if self.tooltip != model.tooltip:
            self.tooltip = model.tooltip

    @staticmethod
    def _build_content(model: TopBarToolsModel) -> Text:
        """Build the indicator body from a frozen tools model."""
        if model.pre_load:
            # Before the first glance load the ⚒ chips hide (never a false
            # zero); the orange bare-monitor chip may still show.
            text = Text("")
            text.append_text(gear_chip(model.bare_monitors, MONITOR_GEAR_HUE))
            return text
        if model.fallback:
            text = icon_count_chip(
                TOOL_RUN_GLYPH, model.live, TOOL_RUN_ACCENT, dim=True
            )
            text.append_text(gear_chip(model.bare_monitors, MONITOR_GEAR_HUE))
            return text
        display = "200+" if model.truncated else None
        # A truncated glance always has runs; keep the chip visible even if
        # the visible slice folded to zero.
        count = model.live or (1 if model.truncated else 0)
        text = icon_count_chip(
            TOOL_RUN_GLYPH, count, TOOL_RUN_ACCENT, display=display, dim=model.stale
        )
        text.append_text(
            icon_count_chip(
                f"{TOOL_RUN_GLYPH}⚠", model.silent, _SILENT_HUE, dim=model.stale
            )
        )
        text.append_text(gear_chip(model.bare_monitors, MONITOR_GEAR_HUE))
        return text
