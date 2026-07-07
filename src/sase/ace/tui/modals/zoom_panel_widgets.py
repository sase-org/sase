"""Hosted panel variants used by the Agents-tab zoom modal."""

from __future__ import annotations

from textual.containers import VerticalScroll

from ..widgets.file_panel import AgentFilePanel
from ..widgets.tools_panel import AgentToolsPanel


class ZoomFilePanel(AgentFilePanel):
    """Agent file panel variant whose scroll container lives inside the modal."""

    def _get_scroll_container(self) -> VerticalScroll | None:
        try:
            return self.screen.query_one("#zoom-file-scroll", VerticalScroll)
        except Exception:
            return None


class ZoomToolsPanel(AgentToolsPanel):
    """Agent tools panel variant whose scroll container lives inside the modal."""

    def _get_scroll_container(self) -> VerticalScroll | None:
        try:
            return self.screen.query_one("#zoom-tools-scroll", VerticalScroll)
        except Exception:
            return None


__all__ = ["ZoomFilePanel", "ZoomToolsPanel"]
