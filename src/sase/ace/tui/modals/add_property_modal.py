"""Add-property picker for the prompt Frontmatter Panel.

The modal lists the frontmatter fields the user has **not** set yet, with the
schema guidance sourced from ``sase-core`` (the same schema that backs the
xprompt LSP), and returns the chosen field name.  The panel then drops into that
field's inline editor or structured sub-form.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from textual import events
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


_RESERVED_ACCELERATORS: Final[frozenset[str]] = frozenset({"j", "k", "q"})
_FALLBACK_ACCELERATORS: Final[str] = "1234567890abcdefghijklmnopqrstuvwxyz"
_KIND_LABELS: Final[dict[str, str]] = {
    "scalar": "scalar",
    "list": "list",
    "structured": "structured",
    "bool_or_list": "bool|list",
    "bool_or_scalar": "bool|scalar",
}


@dataclass(frozen=True)
class AddableProperty:
    """One pickable frontmatter field and the core schema guidance to display."""

    name: str
    description: str
    kind: str
    example: str = ""
    allowed_values: str | None = None


@dataclass(frozen=True)
class _PropertyChoice:
    """A property plus its single-key accelerator."""

    prop: AddableProperty
    key: str


class AddPropertyModal(ModalScreen[str | None]):
    """Pick a frontmatter property to add; dismiss with its name (or ``None``)."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "select_current", "Select"),
        ("j", "cursor_down", "Next"),
        ("k", "cursor_up", "Previous"),
        ("down", "cursor_down", "Next"),
        ("up", "cursor_up", "Previous"),
        ("ctrl+n", "cursor_down", "Next"),
        ("ctrl+p", "cursor_up", "Previous"),
        ("q", "cancel", "Cancel"),
    ]

    def __init__(self, properties: list[AddableProperty]) -> None:
        super().__init__()
        self._properties = properties
        self._choices = _assign_accelerators(properties)
        self._key_to_index = {
            choice.key: index for index, choice in enumerate(self._choices)
        }
        self._selected = 0
        self._name_width = min(
            max((len(prop.name) for prop in properties), default=4),
            14,
        )

    def compose(self) -> ComposeResult:
        """Compose the picker: title, keyed rows, detail strip, and footer."""
        with Container(id="add-property-modal-container"):
            yield Static("Add frontmatter property", id="modal-title")
            with VerticalScroll(id="add-property-list"):
                for index, choice in enumerate(self._choices):
                    yield Static(
                        self._row_text(choice, selected=index == self._selected),
                        id=f"add-property-row-{index}",
                        classes="add-property-row",
                    )
            yield Static("", id="add-property-detail")
            yield Static(self._footer_text(), id="add-property-footer")

    def on_mount(self) -> None:
        """Paint selected-row classes and the initial detail strip."""
        self._refresh()

    def on_key(self, event: events.Key) -> None:
        """Handle modal keys and act as a barrier for printable leftovers."""
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
        if event.key in {"j", "down", "ctrl+n"}:
            event.prevent_default()
            event.stop()
            self.action_cursor_down()
            return
        if event.key in {"k", "up", "ctrl+p"}:
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
            event.stop()

    def action_cancel(self) -> None:
        """Cancel the picker."""
        self.dismiss(None)

    def action_select_current(self) -> None:
        """Select the highlighted property."""
        if not self._choices:
            self.dismiss(None)
            return
        self._select_index(self._selected)

    def action_cursor_down(self) -> None:
        """Move the highlighted row down, clamped to the available choices."""
        self._move(1)

    def action_cursor_up(self) -> None:
        """Move the highlighted row up, clamped to the available choices."""
        self._move(-1)

    def _move(self, delta: int) -> None:
        if not self._choices:
            return
        self._selected = max(0, min(self._selected + delta, len(self._choices) - 1))
        self._refresh()

    def _select_index(self, index: int) -> None:
        self.dismiss(self._choices[index].prop.name)

    def _refresh(self) -> None:
        """Refresh rows and detail after the highlighted choice changes."""
        if not self.is_mounted:
            return
        for index, choice in enumerate(self._choices):
            selected = index == self._selected
            row = self.query_one(f"#add-property-row-{index}", Static)
            row.update(self._row_text(choice, selected=selected))
            row.set_class(selected, "selected")
            if selected:
                row.scroll_visible(animate=False)
        self.query_one("#add-property-detail", Static).update(self._detail_text())

    def _row_text(self, choice: _PropertyChoice, *, selected: bool) -> Text:
        """Render one selectable property row."""
        prop = choice.prop
        marker = "▸" if selected else " "
        key_style = "bold reverse #87D7FF" if selected else "bold #87D7FF"
        name_style = "bold #87D7FF"
        kind_style = "bold #C6A0F6" if selected else "#C6A0F6"
        description = _ellipsize(prop.description, 42)
        text = Text()
        text.append(f"{marker} ", style="bold #87D7FF" if selected else "dim")
        text.append(f" {choice.key} ", style=key_style)
        text.append("  ")
        text.append(f"{prop.name:<{self._name_width}}", style=name_style)
        text.append("  ")
        text.append(f"{_kind_label(prop.kind):<12}", style=kind_style)
        if description:
            text.append(f"  {description}", style="dim")
        return text

    def _detail_text(self) -> Text:
        """Render the detail strip for the highlighted property."""
        if not self._choices:
            return Text("No frontmatter properties are available.", style="dim")
        prop = self._choices[self._selected].prop
        rule = f"── {prop.name} "
        rule += "─" * max(0, 66 - len(rule))
        text = Text(rule, style="#5FD7FF")
        if prop.description:
            text.append("\n")
            text.append(prop.description, style="dim")
        if prop.example:
            text.append("\n")
            text.append("Example   ", style="bold #A6E22E")
            text.append(prop.example, style="#F8F8F2")
        if prop.allowed_values:
            text.append("\n")
            text.append("Accepts   ", style="bold #A6E22E")
            text.append(prop.allowed_values, style="#F8F8F2")
        return text

    def _footer_text(self) -> Text:
        key_list = " ".join(choice.key for choice in self._choices)
        text = Text()
        if key_list:
            text.append(key_list, style="bold #87D7FF")
            text.append("  pick   ·   ", style="dim")
        text.append("j/k move   ·   enter select   ·   esc cancel", style="dim")
        return text


def _assign_accelerators(properties: list[AddableProperty]) -> list[_PropertyChoice]:
    """Assign deterministic unique accelerator keys in display order."""
    used: set[str] = set()
    choices: list[_PropertyChoice] = []
    for prop in properties:
        key = _choose_accelerator(prop.name, used)
        used.add(key)
        choices.append(_PropertyChoice(prop=prop, key=key))
    return choices


def _choose_accelerator(name: str, used: set[str]) -> str:
    candidates = [
        char.lower()
        for char in name
        if char.isalnum()
        and char.lower() not in _RESERVED_ACCELERATORS
        and char.lower() not in used
    ]
    candidates.extend(
        char
        for char in _FALLBACK_ACCELERATORS
        if char not in _RESERVED_ACCELERATORS and char not in used
    )
    if not candidates:
        raise ValueError("no accelerator keys left for add-property picker")
    return candidates[0]


def _kind_label(kind: str) -> str:
    raw = getattr(kind, "value", kind)
    return _KIND_LABELS.get(str(raw), str(raw).replace("_", "|"))


def _ellipsize(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return f"{text[: width - 3]}..."
