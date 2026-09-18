"""Single-key Agents-tab detail view chooser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from ..widgets._agent_detail_panels import DetailLayoutMode, DetailPanelMode

AgentViewSection = Literal["view", "layout"]


@dataclass(frozen=True)
class AgentViewResult:
    """A selected detail-view operation."""

    kind: Literal["mode", "layout", "cycle"]
    mode: DetailPanelMode | None = None
    layout: DetailLayoutMode | None = None
    cycle_direction: Literal[-1, 1] | None = None

    @classmethod
    def mode_choice(cls, mode: DetailPanelMode) -> AgentViewResult:
        return cls("mode", mode=mode)

    @classmethod
    def layout_choice(cls, layout: DetailLayoutMode) -> AgentViewResult:
        return cls("layout", layout=layout)

    @classmethod
    def cycle(cls, direction: Literal[-1, 1]) -> AgentViewResult:
        return cls("cycle", cycle_direction=direction)


@dataclass(frozen=True)
class AgentViewChoice:
    """One visible Agent view modal choice."""

    key: str
    label: str
    subtitle: str
    section: AgentViewSection
    result: AgentViewResult
    enabled: bool = True
    badge: Literal["Current", "Saved"] | None = None
    disabled_reason: str | None = None


class AgentViewModal(ModalScreen[AgentViewResult | None]):
    """Pick an Agents detail view or layout, returning ``None`` when cancelled."""

    BINDINGS = [
        Binding("f", "choose('f')", "File", show=False),
        Binding("t", "choose('t')", "LLM Calls", show=False),
        Binding("0", "choose('0')", "None", show=False),
        Binding("1", "choose('1')", "Metadata Larger", show=False),
        Binding("=", "choose('=')", "Equal Split", show=False),
        Binding("2", "choose('2')", "Secondary Larger", show=False),
        Binding("p", "choose('p')", "Next Layout", show=False),
        Binding("P", "choose('P')", "Previous Layout", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
        Binding("enter", "select_current", "Select", show=False),
        Binding("j", "cursor_down", "Next", show=False),
        Binding("k", "cursor_up", "Previous", show=False),
        Binding("down", "cursor_down", "Next", show=False),
        Binding("up", "cursor_up", "Previous", show=False),
    ]

    def __init__(
        self,
        choices: tuple[AgentViewChoice, ...],
        *,
        selected_key: str,
    ) -> None:
        super().__init__()
        self._choices = choices
        self._selected = self._index_for_key(selected_key)
        if not self._choices[self._selected].enabled:
            self._selected = self._first_enabled_index()
        self._key_to_index = {
            choice.key: index for index, choice in enumerate(self._choices)
        }
        self._dismissed = False
        self._blocked_index: int | None = None

    @property
    def choices(self) -> tuple[AgentViewChoice, ...]:
        """Return the stable visible choices."""
        return self._choices

    def compose(self) -> ComposeResult:
        with Container(id="agent-view-container"):
            yield Static("Agent view", id="agent-view-title")
            yield Static("Press a key to apply.", id="agent-view-guidance")
            with VerticalScroll(id="agent-view-list"):
                yielded_layout_header = False
                yield Static("VIEW", classes="agent-view-section")
                for index, choice in enumerate(self._choices):
                    if choice.section == "layout" and not yielded_layout_header:
                        yielded_layout_header = True
                        yield Static("", classes="agent-view-divider")
                        yield Static("LAYOUT", classes="agent-view-section")
                    yield Static(
                        self._row_text(choice, focused=index == self._selected),
                        id=f"agent-view-row-{index}",
                        classes=self._row_classes(choice, index),
                    )
            yield Static(
                "Up/Down or j/k move - Enter select - Esc cancel",
                id="agent-view-footer",
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

        character = event.character if event.character else ""
        if character in self._key_to_index:
            event.prevent_default()
            event.stop()
            self._select_index(self._key_to_index[character])
            return
        folded_character = character.lower()
        if (
            folded_character
            and folded_character not in {"p"}
            and folded_character in self._key_to_index
        ):
            event.prevent_default()
            event.stop()
            self._select_index(self._key_to_index[folded_character])
            return
        if event.character and event.character.isprintable():
            event.prevent_default()
            event.stop()

    def on_click(self, event: events.Click) -> None:
        """Select a choice when any part of its row is clicked."""
        widget = event.widget
        while widget is not None:
            widget_id = getattr(widget, "id", None)
            prefix = "agent-view-row-"
            if isinstance(widget_id, str) and widget_id.startswith(prefix):
                try:
                    index = int(widget_id.removeprefix(prefix))
                except ValueError:
                    return
                if 0 <= index < len(self._choices):
                    event.prevent_default()
                    event.stop()
                    self._select_index(index)
                return
            widget = getattr(widget, "parent", None)

    def action_cancel(self) -> None:
        self._dismiss_once(None)

    def action_select_current(self) -> None:
        self._select_index(self._selected)

    def action_choose(self, key: str) -> None:
        self._select_index(self._key_to_index[key])

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_cursor_up(self) -> None:
        self._move(-1)

    def _move(self, delta: int) -> None:
        if not any(choice.enabled for choice in self._choices):
            return
        index = self._selected
        for _ in self._choices:
            index = (index + delta) % len(self._choices)
            if self._choices[index].enabled:
                self._selected = index
                self._blocked_index = None
                self._refresh()
                return

    def _select_index(self, index: int) -> None:
        choice = self._choices[index]
        if not choice.enabled:
            self._blocked_index = index
            self._refresh()
            return
        self._dismiss_once(choice.result)

    def _dismiss_once(self, result: AgentViewResult | None) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.dismiss(result)

    def _refresh(self) -> None:
        if not self.is_mounted:
            return
        for index, choice in enumerate(self._choices):
            focused = index == self._selected
            row = self.query_one(f"#agent-view-row-{index}", Static)
            row.update(self._row_text(choice, focused=focused))
            row.set_class(focused, "focused")
            row.set_class(choice.badge == "Current", "current")
            row.set_class(not choice.enabled, "disabled")
            row.set_class(index == self._blocked_index, "blocked")
            if focused:
                row.scroll_visible(animate=False)

    def _row_text(self, choice: AgentViewChoice, *, focused: bool) -> Text:
        disabled = not choice.enabled
        is_blocked = self._choices.index(choice) == self._blocked_index
        pointer_style = "bold #87D7FF" if focused else "dim"
        key_style = "bold black on #87D7FF" if focused else "bold #87D7FF"
        label_style = "dim" if disabled else ("bold #F8F8F2" if focused else "bold")
        badge_style = "bold #A6E22E" if choice.badge == "Current" else "dim"
        subtitle_style = "bold #FFAF5F" if is_blocked else "dim"

        text = Text()
        text.append("> " if focused else "  ", style=pointer_style)
        text.append("[", style="dim")
        text.append(choice.key, style=key_style)
        text.append("] ", style="dim")
        text.append(f"{choice.label:<22}", style=label_style)
        if choice.badge:
            text.append(f" {choice.badge}", style=badge_style)
        text.append("\n    ")
        subtitle = choice.subtitle
        if disabled and choice.disabled_reason:
            subtitle = choice.disabled_reason
        text.append(subtitle, style=subtitle_style)
        return text

    def _row_classes(self, choice: AgentViewChoice, index: int) -> str:
        classes = ["agent-view-row"]
        if index == self._selected:
            classes.append("focused")
        if choice.badge == "Current":
            classes.append("current")
        if not choice.enabled:
            classes.append("disabled")
        return " ".join(classes)

    def _index_for_key(self, key: str) -> int:
        for index, choice in enumerate(self._choices):
            if choice.key == key:
                return index
        return self._first_enabled_index()

    def _first_enabled_index(self) -> int:
        for index, choice in enumerate(self._choices):
            if choice.enabled:
                return index
        return 0


AGENT_VIEW_MODE_CHOICES: Final[tuple[tuple[str, str, DetailPanelMode], ...]] = (
    ("f", "File", DetailPanelMode.AUTO),
    ("t", "LLM Calls", DetailPanelMode.LLM_CALLS),
    ("0", "None", DetailPanelMode.INFO),
)


__all__ = [
    "AGENT_VIEW_MODE_CHOICES",
    "AgentViewChoice",
    "AgentViewModal",
    "AgentViewResult",
]
