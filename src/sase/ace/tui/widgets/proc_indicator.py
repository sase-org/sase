"""Background-procs indicator widget for sase's TUI (epic sase-1ih).

Renders as ``bg: ⚙ N`` with the blue chip for the TUI's own background
work. ToolRun carriers are never counted here; they live under
``tools:`` (see ``ToolsIndicator``).
"""

from typing import Any

from rich.text import Text

from ..proc_gear_chips import PROC_GEAR_HUE, gear_chip
from .top_bar_group import TopBarGroup


class ProcIndicator(TopBarGroup):
    """Shows the TUI's own background procs in the top bar.

    Renders as ``bg: ⚙ N`` with the blue chip only. Hidden when the count
    is zero; clicking opens the Procs tab. The class name and the
    ``#proc-indicator`` id are kept to limit churn.
    """

    GROUP_LABEL = "bg"
    CLICK_ACTION = "open_tasks_panel"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._count = 0
        self._set_body(self._build_content(0))
        self.tooltip = self._build_tooltip(0, "")

    def set_model(self, bg_count: int, tooltip: str) -> None:
        """Update the displayed background count and tooltip.

        Args:
            bg_count: Number of currently running TUI background procs.
            tooltip: Prebuilt ``bg:`` tooltip text.
        """
        if self._count == bg_count and self.tooltip == tooltip:
            return
        self._count = bg_count
        self._set_body(self._build_content(bg_count))
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    @staticmethod
    def _build_content(bg_count: int) -> Text:
        """Build the indicator body."""
        return gear_chip(bg_count, PROC_GEAR_HUE)

    @staticmethod
    def _build_tooltip(bg_count: int, tooltip: str) -> str:
        """Return the prebuilt tooltip, falling back to the empty state."""
        if tooltip:
            return tooltip
        if bg_count > 0:
            noun = "proc" if bg_count == 1 else "procs"
            return f"{bg_count} TUI background {noun}\nClick to open the Procs tab"
        return "No TUI background procs\nClick to open the Procs tab"
