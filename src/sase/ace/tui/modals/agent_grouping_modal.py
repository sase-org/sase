"""Single-key Agents-tab grouping chooser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.models.agent_groups import GroupingMode


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


class AgentGroupingModal(ModalScreen[GroupingMode | None]):
    """Pick an Agents grouping mode, returning ``None`` when cancelled."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("enter", "select_current", "Select"),
        ("j", "cursor_down", "Next"),
        ("k", "cursor_up", "Previous"),
        ("down", "cursor_down", "Next"),
        ("up", "cursor_up", "Previous"),
    ]

    def __init__(self, current_mode: GroupingMode = GroupingMode.STANDARD) -> None:
        super().__init__()
        self._current_mode = current_mode
        self._selected = self._index_for_mode(current_mode)
        self._key_to_index = {
            choice.key: index for index, choice in enumerate(AGENT_GROUPING_CHOICES)
        }
        self._dismissed = False

    @property
    def choices(self) -> tuple[_AgentGroupingChoice, ...]:
        """Return the stable visible choices."""
        return AGENT_GROUPING_CHOICES

    def compose(self) -> ComposeResult:
        with Container(id="agent-grouping-container"):
            yield Static("Group agents by", id="agent-grouping-title")
            yield Static(
                "Press a letter to switch grouping.",
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
                "Up/Down or j/k move - Enter select - Esc cancel",
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
            widget = getattr(widget, "parent", None)

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
            min(self._selected + delta, len(AGENT_GROUPING_CHOICES) - 1),
        )
        self._refresh()

    def _select_index(self, index: int) -> None:
        self._dismiss_once(AGENT_GROUPING_CHOICES[index].mode)

    def _dismiss_once(self, result: GroupingMode | None) -> None:
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

    @staticmethod
    def _index_for_mode(mode: GroupingMode) -> int:
        for index, choice in enumerate(AGENT_GROUPING_CHOICES):
            if choice.mode is mode:
                return index
        return 0


__all__ = [
    "AGENT_GROUPING_CHOICES",
    "AgentGroupingModal",
]
