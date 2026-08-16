"""Hosted panel variants used by the Agents-tab zoom modal."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..models.agent import Agent
from ..widgets.file_panel import AgentFilePanel
from ..widgets.file_panel._file_list import FileSourceLabel
from ..widgets.tools_panel import AgentToolsPanel

_RAIL_LABEL_MAX_WIDTH = 22


def _truncate_rail_label(label: str) -> str:
    """Return a rail label that fits the fixed-width file list."""
    if len(label) <= _RAIL_LABEL_MAX_WIDTH:
        return label
    return f"{label[: _RAIL_LABEL_MAX_WIDTH - 3]}..."


class ZoomFilePanel(AgentFilePanel):
    """Agent file panel variant whose scroll container lives inside the modal."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._file_list_frozen = False
        self._frozen_file_list: tuple[str, ...] = ()
        self._frozen_default_value: str | None = None

    @property
    def is_file_list_frozen(self) -> bool:
        """Return whether the modal file list is fixed for this zoom session."""
        return self._file_list_frozen

    def freeze_current_list(self) -> None:
        """Freeze the current non-empty file list for the life of the modal."""
        if self._file_list_frozen or not self._file_list:
            return
        self._current_file_index = min(
            max(self._current_file_index, 0),
            len(self._file_list) - 1,
        )
        self._frozen_file_list = tuple(self._file_list)
        self._frozen_default_value = self._file_list[self._current_file_index]
        self._file_list_frozen = True

    def _get_scroll_container(self) -> VerticalScroll | None:
        try:
            return self.screen.query_one("#zoom-file-scroll", VerticalScroll)
        except Exception:
            return None

    def _desired_file_list(self, agent: Agent) -> tuple[list[str], str | None]:
        if self._file_list_frozen and self._frozen_file_list:
            return list(self._frozen_file_list), self._frozen_default_value
        return super()._desired_file_list(agent)

    def _reconcile_file_list(
        self,
        agent: Agent,
        *,
        allow_initial_display: bool,
    ) -> None:
        super()._reconcile_file_list(
            agent,
            allow_initial_display=allow_initial_display,
        )
        self.freeze_current_list()

    def set_file_list(self, files: list[str], start_index: int = 0) -> None:
        if not self._file_list_frozen:
            super().set_file_list(files, start_index=start_index)
            return
        if not self._has_displayed_content and self._file_list:
            # The seeded file list bypassed set_file_list's normal
            # _note_slot_change call, so the anchor slot key was never
            # established for this frozen list — establish it now, before
            # the first real render.
            self._note_slot_change(self._current_anchor_key())
            self._display_file_at_current_index()


class ZoomFileRail(Static):
    """Slim file list shown beside multi-file zoom content."""

    def update_entries(
        self,
        entries: Sequence[FileSourceLabel],
        active_index: int,
    ) -> None:
        """Render file source entries and mark the active file."""
        count = len(entries)
        self.border_title = f"FILES ({count})" if count else "FILES"
        if count <= 1:
            self.add_class("collapsed")
            self.update("")
            return

        self.remove_class("collapsed")
        active_index = min(max(active_index, 0), count - 1)
        body = Text(no_wrap=True, overflow="ellipsis")
        for index, entry in enumerate(entries):
            active = index == active_index
            row_style = "bold black on #A8FF60" if active else "dim"
            tag_style = row_style if active else "bold #87D7FF"
            body.append("● " if active else "  ", style=row_style)
            body.append(entry.tag[:4].ljust(4), style=tag_style)
            body.append(" ", style=row_style)
            body.append(_truncate_rail_label(entry.label), style=row_style)
            if index < count - 1:
                body.append("\n")
        self.update(body)

        scroll_to = getattr(self, "scroll_to", None)
        if callable(scroll_to):
            self.call_after_refresh(
                lambda: scroll_to(
                    y=max(active_index - 1, 0),
                    animate=False,
                    immediate=True,
                )
            )


class ZoomToolsPanel(AgentToolsPanel):
    """Agent tools panel variant whose scroll container lives inside the modal."""

    def _get_scroll_container(self) -> VerticalScroll | None:
        try:
            return self.screen.query_one("#zoom-tools-scroll", VerticalScroll)
        except Exception:
            return None


__all__ = ["ZoomFilePanel", "ZoomFileRail", "ZoomToolsPanel"]
