"""Single-keypress chooser for acting on an Agents-tab node."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

AgentActionSection = Literal["gate", "patch"]

#: Guidance footer shared by the chooser modal.
_AGENT_ACTION_FOOTER: Final = "Up/Down or j/k move - Enter select - Esc cancel"


@dataclass(frozen=True)
class AgentActionChoice:
    """One visible agent-action chooser choice."""

    result: str
    section: AgentActionSection
    label: str
    detail: str | None
    glyph: str
    glyph_style: str
    badge: str | None
    badge_style: str | None
    age: str | None


def _badge_text(choice: AgentActionChoice) -> str:
    if choice.badge and choice.age:
        return f"{choice.badge} · {choice.age}"
    return choice.badge or choice.age or ""


class AgentActionChooserModal(ModalScreen[str | None]):
    """Pick one action for an agent node, returning ``None`` when cancelled.

    The modal takes a generic view model and knows nothing about ``Agent``
    rows or notifications: callers pass ordered choices (gates first, the
    Patch last) plus a title such as ``"Act on foo.bar"``. Direct keys are
    assigned deterministically: a lone gate row gets ``g``; several gate
    rows get ``1``-``9`` in display order with ``g`` kept as a hidden alias
    for the first gate; the Patch row gets ``p``.
    """

    BINDINGS = [
        Binding("enter", "select_current", "Select", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
        Binding("j", "cursor_down", "Next", show=False),
        Binding("k", "cursor_up", "Previous", show=False),
        Binding("down", "cursor_down", "Next", show=False),
        Binding("up", "cursor_up", "Previous", show=False),
    ]

    def __init__(
        self,
        choices: tuple[AgentActionChoice, ...] | list[AgentActionChoice],
        *,
        title: str,
    ) -> None:
        super().__init__()
        normalized = tuple(choices)
        if not normalized:
            raise ValueError("AgentActionChooserModal needs at least one choice")
        self._choices = normalized
        self._title_text = title
        self._selected = 0
        self._key_to_index = self._assign_keys(normalized)
        self._dismissed = False

    @staticmethod
    def _assign_keys(choices: tuple[AgentActionChoice, ...]) -> dict[str, int]:
        gate_indexes = [
            index for index, choice in enumerate(choices) if choice.section == "gate"
        ]
        keys: dict[str, int] = {}
        if len(gate_indexes) == 1:
            keys["g"] = gate_indexes[0]
        else:
            for position, index in enumerate(gate_indexes):
                if position < 9:
                    keys[str(position + 1)] = index
            if gate_indexes:
                keys["g"] = gate_indexes[0]
        for index, choice in enumerate(choices):
            if choice.section == "patch":
                keys["p"] = index
        return keys

    @property
    def choices(self) -> tuple[AgentActionChoice, ...]:
        """Return the stable visible choices in display order."""
        return self._choices

    @property
    def key_to_index(self) -> dict[str, int]:
        """Return the assigned direct key for each row index."""
        return dict(self._key_to_index)

    @property
    def primary_label(self) -> str:
        """Return the label of the primary (first) action."""
        return self._choices[0].label

    @property
    def guidance_text(self) -> str:
        """Return the guidance line naming the primary action."""
        return f"⏎ again → {self.primary_label} · or press a key"

    def display_key(self, index: int) -> str:
        """Return the keycap shown for one row."""
        choice = self._choices[index]
        if choice.section == "patch":
            return "p"
        gate_indexes = [
            i for i, item in enumerate(self._choices) if item.section == "gate"
        ]
        if len(gate_indexes) == 1:
            return "g"
        position = gate_indexes.index(index)
        if position < 9:
            return str(position + 1)
        return ""

    def compose(self) -> ComposeResult:
        with Container(id="agent-action-container"):
            yield Static(self._title_text, id="agent-action-title")
            yield Static(self.guidance_text, id="agent-action-guidance")
            with VerticalScroll(id="agent-action-list"):
                gate_indexes = [
                    index
                    for index, choice in enumerate(self._choices)
                    if choice.section == "gate"
                ]
                patch_indexes = [
                    index
                    for index, choice in enumerate(self._choices)
                    if choice.section == "patch"
                ]
                if gate_indexes:
                    header = "GATE" if len(gate_indexes) == 1 else "GATES"
                    yield Static(header, classes="agent-action-section")
                    for index in gate_indexes:
                        yield Static(
                            self._row_renderable(
                                index, focused=index == self._selected
                            ),
                            id=f"agent-action-row-{index}",
                            classes=self._row_classes(index),
                        )
                if patch_indexes:
                    yield Static("PATCH", classes="agent-action-section")
                    for index in patch_indexes:
                        yield Static(
                            self._row_renderable(
                                index, focused=index == self._selected
                            ),
                            id=f"agent-action-row-{index}",
                            classes=self._row_classes(index),
                        )
            yield Static(_AGENT_ACTION_FOOTER, id="agent-action-footer")

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
        if event.character and event.character.isprintable():
            event.prevent_default()
            event.stop()

    def on_click(self, event: events.Click) -> None:
        """Select a choice when any part of its row is clicked."""
        widget = event.widget
        while widget is not None:
            widget_id = getattr(widget, "id", None)
            prefix = "agent-action-row-"
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

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_cursor_up(self) -> None:
        self._move(-1)

    def _move(self, delta: int) -> None:
        self._selected = (self._selected + delta) % len(self._choices)
        self._refresh()

    def _select_index(self, index: int) -> None:
        self._dismiss_once(self._choices[index].result)

    def _dismiss_once(self, result: str | None) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.dismiss(result)

    def _refresh(self) -> None:
        if not self.is_mounted:
            return
        for index in range(len(self._choices)):
            focused = index == self._selected
            row = self.query_one(f"#agent-action-row-{index}", Static)
            row.update(self._row_renderable(index, focused=focused))
            row.set_class(focused, "focused")
            if focused:
                row.scroll_visible(animate=False)

    def _row_renderable(self, index: int, *, focused: bool) -> Table:
        choice = self._choices[index]
        pointer_style = "bold #87D7FF" if focused else "dim"
        key_style = "bold black on #87D7FF" if focused else "bold #87D7FF"

        first = Text(no_wrap=True, overflow="ellipsis")
        first.append("› " if focused else "  ", style=pointer_style)
        display_key = self.display_key(index)
        if display_key:
            first.append("[", style="dim")
            first.append(display_key, style=key_style)
            first.append("] ", style="dim")
        if choice.glyph:
            first.append(choice.glyph, style=choice.glyph_style)
            first.append(" ", style="dim")
        first.append(choice.label, style="bold #F8F8F2")

        badge = Text(no_wrap=True, overflow="ellipsis")
        badge_text = _badge_text(choice)
        if badge_text:
            badge.append(badge_text, style=choice.badge_style or "")

        table = Table.grid(expand=True)
        table.add_column(ratio=1, overflow="ellipsis")
        table.add_column(justify="right", no_wrap=True)
        table.add_row(first, badge)

        if choice.detail:
            second = Text(no_wrap=True, overflow="ellipsis")
            second.append("      ", style="dim")
            second.append(choice.detail, style="dim")
            table.add_row(second, Text())
        return table

    def _row_classes(self, index: int) -> str:
        classes = ["agent-action-row"]
        if index == self._selected:
            classes.append("focused")
        return " ".join(classes)


__all__ = [
    "AgentActionChoice",
    "AgentActionChooserModal",
]
