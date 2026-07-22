"""Reusable keyboard-and-mouse property picker.

The frontmatter panel originally owned a polished add-property modal.  AXE
schema forms need the same interaction without frontmatter-specific copy or
types, so the implementation lives here and the legacy modal is now a thin
adapter.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from rich.text import Text
from textual import events
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
class PropertyPickerItem:
    """One pickable property and the guidance shown for it."""

    name: str
    description: str
    kind: str
    example: str = ""
    allowed_values: str | None = None


@dataclass(frozen=True)
class PropertyPickerChoice:
    """A property plus its deterministic single-key accelerator."""

    item: PropertyPickerItem
    key: str

    @property
    def prop(self) -> PropertyPickerItem:
        """Backward-compatible alias used by the frontmatter picker."""
        return self.item


class PropertyPickerModal(ModalScreen[str | None]):
    """Pick one property, returning its name or ``None`` when cancelled."""

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

    def __init__(
        self,
        properties: Iterable[PropertyPickerItem],
        *,
        title: str = "Add property",
        guidance: str = "",
        empty_message: str = "No properties are available.",
        dom_prefix: str = "property-picker",
        generic_style: bool = True,
    ) -> None:
        super().__init__()
        self.set_class(generic_style, "-generic")
        self._properties = list(properties)
        self._choices = assign_property_accelerators(self._properties)
        self._key_to_index = {
            choice.key: index for index, choice in enumerate(self._choices)
        }
        self._selected = 0
        self._title_text = title
        self._guidance = guidance
        self._empty_message = empty_message
        self._dom_prefix = dom_prefix
        self._name_width = min(
            max((len(prop.name) for prop in self._properties), default=4),
            14,
        )

    @property
    def choices(self) -> tuple[PropertyPickerChoice, ...]:
        """Return the immutable choices for tests and embedding callers."""
        return tuple(self._choices)

    def _dom_id(self, suffix: str) -> str:
        return f"{self._dom_prefix}-{suffix}"

    def compose(self) -> ComposeResult:
        """Compose title, choices, live detail, and keyboard guidance."""
        with Container(id=self._dom_id("modal-container")):
            yield Static(self._title_text, id="modal-title")
            if self._guidance:
                yield Static(self._guidance, id=self._dom_id("guidance"))
            with VerticalScroll(id=self._dom_id("list")):
                for index, choice in enumerate(self._choices):
                    yield Static(
                        self._row_text(choice, selected=index == self._selected),
                        id=self._dom_id(f"row-{index}"),
                        classes=self._row_classes,
                    )
            yield Static("", id=self._dom_id("detail"))
            yield Static(self._footer_text(), id=self._dom_id("footer"))

    @property
    def _row_classes(self) -> str:
        return "property-picker-row"

    def on_mount(self) -> None:
        self._refresh()

    def on_key(self, event: events.Key) -> None:
        """Handle direct accelerators and contain printable key leftovers."""
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

    def on_click(self, event: events.Click) -> None:
        """Select a row with the mouse."""
        widget_id = getattr(event.widget, "id", None)
        prefix = self._dom_id("row-")
        if not isinstance(widget_id, str) or not widget_id.startswith(prefix):
            return
        try:
            index = int(widget_id.removeprefix(prefix))
        except ValueError:
            return
        if 0 <= index < len(self._choices):
            event.stop()
            event.prevent_default()
            self._select_index(index)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select_current(self) -> None:
        if not self._choices:
            self.dismiss(None)
            return
        self._select_index(self._selected)

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_cursor_up(self) -> None:
        self._move(-1)

    def _move(self, delta: int) -> None:
        if not self._choices:
            return
        self._selected = max(0, min(self._selected + delta, len(self._choices) - 1))
        self._refresh()

    def _select_index(self, index: int) -> None:
        self.dismiss(self._choices[index].item.name)

    def _refresh(self) -> None:
        if not self.is_mounted:
            return
        for index, choice in enumerate(self._choices):
            selected = index == self._selected
            row = self.query_one(f"#{self._dom_id(f'row-{index}')}", Static)
            row.update(self._row_text(choice, selected=selected))
            row.set_class(selected, "selected")
            if selected:
                row.scroll_visible(animate=False)
        self.query_one(f"#{self._dom_id('detail')}", Static).update(self._detail_text())

    def _row_text(self, choice: PropertyPickerChoice, *, selected: bool) -> Text:
        item = choice.item
        marker = "▸" if selected else " "
        key_style = "bold reverse #87D7FF" if selected else "bold #87D7FF"
        kind_style = "bold #C6A0F6" if selected else "#C6A0F6"
        description = _ellipsize(item.description, 42)
        text = Text()
        text.append(f"{marker} ", style="bold #87D7FF" if selected else "dim")
        text.append(f" {choice.key} ", style=key_style)
        text.append("  ")
        text.append(f"{item.name:<{self._name_width}}", style="bold #87D7FF")
        text.append("  ")
        text.append(f"{_kind_label(item.kind):<12}", style=kind_style)
        if description:
            text.append(f"  {description}", style="dim")
        return text

    def _detail_text(self) -> Text:
        if not self._choices:
            return Text(self._empty_message, style="dim")
        item = self._choices[self._selected].item
        rule = f"── {item.name} "
        rule += "─" * max(0, 66 - len(rule))
        text = Text(rule, style="#5FD7FF")
        if item.description:
            text.append("\n")
            text.append(item.description, style="dim")
        if item.example:
            text.append("\n")
            text.append("Example   ", style="bold #A6E22E")
            text.append(item.example, style="#F8F8F2")
        if item.allowed_values:
            text.append("\n")
            text.append("Accepts   ", style="bold #A6E22E")
            text.append(item.allowed_values, style="#F8F8F2")
        return text

    def _footer_text(self) -> Text:
        key_list = " ".join(choice.key for choice in self._choices)
        text = Text()
        if key_list:
            text.append(key_list, style="bold #87D7FF")
            text.append("  pick   ·   ", style="dim")
        text.append("j/k move   ·   enter select   ·   esc cancel", style="dim")
        return text


def assign_property_accelerators(
    properties: Iterable[PropertyPickerItem],
) -> list[PropertyPickerChoice]:
    """Assign deterministic unique accelerator keys in display order."""
    used: set[str] = set()
    choices: list[PropertyPickerChoice] = []
    for item in properties:
        key = choose_property_accelerator(item.name, used)
        used.add(key)
        choices.append(PropertyPickerChoice(item=item, key=key))
    return choices


def choose_property_accelerator(name: str, used: set[str]) -> str:
    """Choose the first available name character, then a stable fallback."""
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
        raise ValueError("no accelerator keys left for property picker")
    return candidates[0]


def _kind_label(kind: str) -> str:
    raw = getattr(kind, "value", kind)
    return _KIND_LABELS.get(str(raw), str(raw).replace("_", "|"))


def _ellipsize(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return f"{value[: width - 3]}..."


__all__ = [
    "PropertyPickerChoice",
    "PropertyPickerItem",
    "PropertyPickerModal",
    "assign_property_accelerators",
    "choose_property_accelerator",
]

# Descriptive alias for callers that treat picker inputs as records.
PropertyPickerRecord = PropertyPickerItem
