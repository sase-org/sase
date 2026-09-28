"""Single-key Agents-tab grouping chooser with the o/O layout ladder."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panel_layout import (
    AgentPanelLayout,
    available_panel_layouts,
    layout_description,
    layout_short_label,
    next_panel_layout,
    prev_panel_layout,
)


class AgentGroupingAction(Enum):
    """Non-mode actions available from the Agents grouping modal."""

    TOGGLE_PANELS = "toggle_panels"


AgentGroupingResult = GroupingMode | AgentGroupingAction | AgentPanelLayout | None


@dataclass(frozen=True)
class _AgentGroupingChoice:
    """One visible grouping choice in the Agents grouping modal."""

    key: str
    label: str
    subtitle: str
    mode: GroupingMode


AGENT_GROUPING_CHOICES: Final[tuple[_AgentGroupingChoice, ...]] = (
    _AgentGroupingChoice(
        "p",
        "Project",
        "Projects and their Patches",
        GroupingMode.STANDARD,
    ),
    _AgentGroupingChoice(
        "d",
        "Date",
        "Recent date buckets and time groups",
        GroupingMode.BY_DATE,
    ),
    _AgentGroupingChoice(
        "s",
        "Status",
        "Attention first, then activity and completion",
        GroupingMode.BY_STATUS,
    ),
    _AgentGroupingChoice(
        "m",
        "Machine",
        "This machine and remotes, grouped by status",
        GroupingMode.BY_MACHINE,
    ),
)

_LAYOUT_HEADING_HINT = "o next · O back"
_SEGMENT_JOIN = "   "
_SELECTED_SEGMENT_GLYPH = "◉"
_UNSELECTED_SEGMENT_GLYPH = "○"


class AgentGroupingModal(ModalScreen[AgentGroupingResult]):
    """Pick an Agents grouping mode or a panel-layout ladder level."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("enter", "select_current", "Select"),
        ("j", "cursor_down", "Next"),
        ("k", "cursor_up", "Previous"),
        ("down", "cursor_down", "Next"),
        ("up", "cursor_up", "Previous"),
    ]

    def __init__(
        self,
        current_mode: GroupingMode = GroupingMode.STANDARD,
        *,
        current_panel_grouped: bool = False,
        current_layout: AgentPanelLayout | None = None,
        available_layouts: tuple[AgentPanelLayout, ...] | None = None,
        active_tab_label: str = "",
    ) -> None:
        super().__init__()
        self._current_mode = current_mode
        if current_layout is None:
            current_layout = (
                AgentPanelLayout.MERGED
                if current_panel_grouped
                else AgentPanelLayout.SPLIT
            )
        self._current_layout = current_layout
        if available_layouts is None:
            available_layouts = available_panel_layouts(
                current_layout is AgentPanelLayout.ALL_TABS
            )
            if current_layout not in available_layouts:
                available_layouts = (
                    AgentPanelLayout.SPLIT,
                    AgentPanelLayout.MERGED,
                )
        self._available_layouts = tuple(available_layouts)
        self._active_tab_label = active_tab_label
        self._selected = self._index_for_mode(current_mode)
        self._key_to_index = {
            choice.key: index for index, choice in enumerate(AGENT_GROUPING_CHOICES)
        }
        self._layout_index = len(AGENT_GROUPING_CHOICES)
        self._row_count = self._layout_index + 1
        try:
            self._layout_highlight = self._available_layouts.index(current_layout)
        except ValueError:
            self._layout_highlight = 0
        self._layout_spans: tuple[tuple[int, int, AgentPanelLayout], ...] = ()
        self._dismissed = False

    @property
    def choices(self) -> tuple[_AgentGroupingChoice, ...]:
        """Return the stable visible choices."""
        return AGENT_GROUPING_CHOICES

    @property
    def current_layout(self) -> AgentPanelLayout:
        """Return the ladder level the modal was opened with."""
        return self._current_layout

    @property
    def highlighted_layout(self) -> AgentPanelLayout:
        """Return the currently highlighted ladder segment."""
        return self._available_layouts[self._layout_highlight]

    def compose(self) -> ComposeResult:
        with Container(id="agent-grouping-container"):
            yield Static("Group agents by", id="agent-grouping-title")
            yield Static(
                "Press a letter to switch grouping or panel layout.",
                id="agent-grouping-guidance",
            )
            with VerticalScroll(id="agent-grouping-list"):
                for index, choice in enumerate(AGENT_GROUPING_CHOICES):
                    yield Static(
                        self._row_text(choice, focused=index == self._selected),
                        id=f"agent-grouping-row-{index}",
                        classes=self._row_classes(choice, index),
                    )
                yield Static(
                    self._layout_heading_text(),
                    id="agent-panel-layout-heading",
                    classes="agent-grouping-section-heading",
                )
                yield Static(
                    self._layout_row_text(focused=self._selected == self._layout_index),
                    id="agent-panel-layout-row",
                    classes=self._layout_row_classes(),
                )
            yield Static(
                "Up/Down or j/k move - Enter select - Esc cancel - o/O layout",
                id="agent-grouping-footer",
            )

    def on_mount(self) -> None:
        self._refresh()

    def on_key(self, event: events.Key) -> None:
        """Handle direct choices and contain unused printable keys."""
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.action_select_current()
            return
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.action_cancel()
            return
        if event.key in {"j", "down"}:
            event.prevent_default()
            event.stop()
            self.action_cursor_down()
            return
        if event.key in {"k", "up"}:
            event.prevent_default()
            event.stop()
            self.action_cursor_up()
            return
        if event.key == "q":
            event.prevent_default()
            event.stop()
            self.action_cancel()
            return
        if self._selected == self._layout_index and event.key in {
            "h",
            "left",
            "l",
            "right",
        }:
            event.prevent_default()
            event.stop()
            self._move_layout_highlight(-1 if event.key in {"h", "left"} else 1)
            return

        if event.character == "o":
            event.prevent_default()
            event.stop()
            self._step_layout(forward=True)
            return
        if event.character == "O":
            # An explicit ``O`` branch: without it the key is lowercased
            # below and swallowed as an unused printable.
            event.prevent_default()
            event.stop()
            self._step_layout(forward=False)
            return

        character = event.character.lower() if event.character else ""
        if character in self._key_to_index:
            event.prevent_default()
            event.stop()
            self._select_index(self._key_to_index[character])
            return
        if event.character and event.character.isprintable():
            event.prevent_default()
            event.stop()

    def on_click(self, event: events.Click) -> None:
        """Select a choice when any part of its row is clicked."""
        widget = event.widget
        while widget is not None:
            widget_id = getattr(widget, "id", None)
            prefix = "agent-grouping-row-"
            if isinstance(widget_id, str) and widget_id.startswith(prefix):
                try:
                    index = int(widget_id.removeprefix(prefix))
                except ValueError:
                    return
                if 0 <= index < len(AGENT_GROUPING_CHOICES):
                    event.prevent_default()
                    event.stop()
                    self._select_index(index)
                return
            if widget_id == "agent-panel-layout-row":
                event.prevent_default()
                event.stop()
                self._select_layout_at_click(event, widget)
                return
            widget = getattr(widget, "parent", None)

    def _select_layout_at_click(self, event: events.Click, widget: object) -> None:
        """Dismiss with the clicked ladder segment (or the highlight)."""
        try:
            from textual.widget import Widget

            offset = (
                event.get_content_offset(widget) if isinstance(widget, Widget) else None
            )
        except Exception:
            offset = None
        if offset is not None and offset.y <= 0:
            for start, end, level in self._layout_spans:
                if start <= offset.x < end:
                    self._dismiss_once(level)
                    return
        self._dismiss_once(self.highlighted_layout)

    def action_cancel(self) -> None:
        self._dismiss_once(None)

    def action_select_current(self) -> None:
        self._select_index(self._selected)

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_cursor_up(self) -> None:
        self._move(-1)

    def _move(self, delta: int) -> None:
        self._selected = max(
            0,
            min(self._selected + delta, self._row_count - 1),
        )
        self._refresh()

    def _move_layout_highlight(self, delta: int) -> None:
        count = len(self._available_layouts)
        self._layout_highlight = (self._layout_highlight + delta) % count
        self._refresh()

    def _step_layout(self, *, forward: bool) -> None:
        """Dismiss with the next (``o``) or previous (``O``) ladder level."""
        if forward:
            level = next_panel_layout(self.highlighted_layout, self._available_layouts)
        else:
            level = prev_panel_layout(self.highlighted_layout, self._available_layouts)
        self._dismiss_once(level)

    def _select_index(self, index: int) -> None:
        if index == self._layout_index:
            self._dismiss_once(self.highlighted_layout)
            return
        self._dismiss_once(AGENT_GROUPING_CHOICES[index].mode)

    def _dismiss_once(self, result: AgentGroupingResult) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.dismiss(result)

    def _refresh(self) -> None:
        if not self.is_mounted:
            return
        for index, choice in enumerate(AGENT_GROUPING_CHOICES):
            focused = index == self._selected
            row = self.query_one(f"#agent-grouping-row-{index}", Static)
            row.update(self._row_text(choice, focused=focused))
            row.set_class(focused, "focused")
            row.set_class(choice.mode is self._current_mode, "current")
            if focused:
                row.scroll_visible(animate=False)
        layout_focused = self._selected == self._layout_index
        layout_row = self.query_one("#agent-panel-layout-row", Static)
        layout_row.update(self._layout_row_text(focused=layout_focused))
        layout_row.set_class(layout_focused, "focused")
        if layout_focused:
            layout_row.scroll_visible(animate=False)

    def _row_text(self, choice: _AgentGroupingChoice, *, focused: bool) -> Text:
        is_current = choice.mode is self._current_mode
        pointer_style = "bold #87D7FF" if focused else "dim"
        key_style = "bold black on #87D7FF" if focused else "bold #87D7FF"
        label_style = "bold #F8F8F2" if focused else "bold"
        badge_style = "bold #A6E22E" if is_current else "dim"

        text = Text()
        text.append("> " if focused else "  ", style=pointer_style)
        text.append("[", style="dim")
        text.append(choice.key, style=key_style)
        text.append("] ", style="dim")
        text.append(f"{choice.label:<9}", style=label_style)
        if is_current:
            text.append(" Current", style=badge_style)
        text.append("\n    ")
        text.append(choice.subtitle, style="dim")
        return text

    def _row_classes(self, choice: _AgentGroupingChoice, index: int) -> str:
        classes = ["agent-grouping-row"]
        if index == self._selected:
            classes.append("focused")
        if choice.mode is self._current_mode:
            classes.append("current")
        return " ".join(classes)

    def _layout_heading_text(self) -> Text:
        text = Text()
        text.append("Panel layout", style="bold")
        text.append(" " * 4, style="dim")
        text.append(_LAYOUT_HEADING_HINT, style="dim")
        return text

    def _layout_row_text(self, *, focused: bool) -> Text:
        pointer_style = "bold #87D7FF" if focused else "dim"
        label_style = "bold #F8F8F2" if focused else "bold"

        text = Text()
        text.append("> " if focused else "  ", style=pointer_style)
        spans: list[tuple[int, int, AgentPanelLayout]] = []
        column = cell_len(text.plain)
        for position, level in enumerate(self._available_layouts):
            if position > 0:
                text.append(_SEGMENT_JOIN, style="dim")
                column += cell_len(_SEGMENT_JOIN)
            highlighted = position == self._layout_highlight
            is_current = level is self._current_layout
            glyph = (
                _SELECTED_SEGMENT_GLYPH if highlighted else _UNSELECTED_SEGMENT_GLYPH
            )
            glyph_style = (
                "bold black on #87D7FF"
                if focused and highlighted
                else ("bold #87D7FF" if highlighted else "dim")
            )
            segment_label = layout_short_label(level)
            start = column
            text.append(glyph + " ", style=glyph_style)
            column += cell_len(glyph + " ")
            text.append(segment_label, style=label_style)
            column += cell_len(segment_label)
            if is_current:
                text.append(" ✓", style="bold #A6E22E")
                column += cell_len(" ✓")
            spans.append((start, column, level))
        self._layout_spans = tuple(spans)
        text.append("\n    ")
        text.append(
            layout_description(self.highlighted_layout, self._active_tab_label),
            style="dim",
        )
        return text

    def _layout_row_classes(self) -> str:
        classes = ["agent-grouping-row", "agent-panel-layout-row"]
        if self._selected == self._layout_index:
            classes.append("focused")
        return " ".join(classes)

    @staticmethod
    def _index_for_mode(mode: GroupingMode) -> int:
        for index, choice in enumerate(AGENT_GROUPING_CHOICES):
            if choice.mode is mode:
                return index
        return 0


__all__ = [
    "AGENT_GROUPING_CHOICES",
    "AgentGroupingAction",
    "AgentGroupingModal",
    "AgentGroupingResult",
]
