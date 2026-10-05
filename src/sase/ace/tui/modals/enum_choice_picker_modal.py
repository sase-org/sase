"""Searchable picker for large enum choice sets in typed forms."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.macro.models import InputArg

_VISISBLE_ROWS = 12


class EnumChoicePickerModal(ModalScreen[str | None]):
    """Pick one canonical enum value; dismisses with the value or None."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "select_current", "Select"),
    ]

    def __init__(
        self,
        arg: InputArg,
        *,
        current: str = "",
        title: str | None = None,
    ) -> None:
        super().__init__()
        self._arg = arg
        self._query = ""
        self._current = current
        self._rows: list[dict] = []
        self._selected = 0
        self._title = title or f"{arg.name} · choice"
        self._refresh_rows()

    def compose(self) -> ComposeResult:
        with Container(id="enum-picker-container"):
            yield Static(self._title, id="enum-picker-title")
            with VerticalScroll(id="enum-picker-list"):
                for index in range(_VISISBLE_ROWS):
                    yield Static("", id=f"enum-picker-row-{index}")
            yield Static("", id="enum-picker-query")
            yield Static(
                "type to filter · enter select · esc cancel", id="enum-picker-footer"
            )

    def on_mount(self) -> None:
        self._refresh_view()

    def on_key(self, event: events.Key) -> None:
        key = event.key
        if key == "escape":
            event.prevent_default()
            event.stop()
            self.dismiss(None)
            return
        if key == "enter":
            event.prevent_default()
            event.stop()
            self._accept_current()
            return
        if key in ("down", "ctrl+n", "j"):
            event.prevent_default()
            event.stop()
            self._move(1)
            return
        if key in ("up", "ctrl+p", "k"):
            event.prevent_default()
            event.stop()
            self._move(-1)
            return
        if key == "backspace":
            event.prevent_default()
            event.stop()
            if self._query:
                self._query = self._query[:-1]
                self._refresh_rows()
                self._refresh_view()
            return
        char = event.character
        if char is not None and char.isprintable():
            event.prevent_default()
            event.stop()
            self._query += char
            self._refresh_rows()
            self._refresh_view()
            return
        event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select_current(self) -> None:
        self._accept_current()

    def _accept_current(self) -> None:
        if not self._rows:
            self.dismiss(None)
            return
        self.dismiss(str(self._rows[self._selected]["value"]))

    def _move(self, delta: int) -> None:
        if not self._rows:
            return
        self._selected = max(0, min(self._selected + delta, len(self._rows) - 1))
        self._refresh_view()

    def _refresh_rows(self) -> None:
        try:
            from sase.ace.tui.widgets._macro_arg_choice_adapter import (
                hint_to_wire,
            )
            from sase.core.rust import require_rust_binding
            from sase.ace.tui.widgets._macro_arg_assist_inputs import (
                input_hint_from_input_arg,
            )

            hint = input_hint_from_input_arg(self._arg, 0)
            assert hint is not None
            candidates = require_rust_binding("macro_argument_choice_candidates")(
                {
                    "hint": hint_to_wire(hint),
                    "partial": self._query,
                    "replacement": "",
                    "selected": [],
                }
            )
            self._rows = list(candidates)
        except Exception:
            query = self._query.lower()
            rows: list[dict] = []
            for index, choice in enumerate(self._arg.choices):
                if query and query not in choice.value.lower():
                    continue
                rows.append(
                    {
                        "value": choice.value,
                        "label": choice.label,
                        "description": choice.description,
                        "index": index,
                        "is_default": False,
                    }
                )
            self._rows = rows
        # Reopen shows the current selection when the query is empty.
        if not self._query and self._current:
            for index, row in enumerate(self._rows):
                if str(row["value"]) == self._current:
                    self._selected = index
                    break
            else:
                self._selected = 0
        else:
            self._selected = min(self._selected, max(0, len(self._rows) - 1))

    def _refresh_view(self) -> None:
        if not self.is_mounted:
            return
        for index in range(_VISISBLE_ROWS):
            widget = self.query_one(f"#enum-picker-row-{index}", Static)
            if index < len(self._rows):
                row = self._rows[index]
                widget.update(self._row_text(row, selected=index == self._selected))
            else:
                widget.update("")
        query_widget = self.query_one("#enum-picker-query", Static)
        query_widget.update(f"> {self._query}")

    def _row_text(self, row: dict, *, selected: bool) -> Text:
        text = Text()
        text.append("▸ " if selected else "  ", style="bold" if selected else "dim")
        # Canonical value in the main column; free text as plain Rich text.
        text.append(
            Text(str(row["value"])).plain,
            style="bold yellow" if selected else "yellow",
        )
        label = row.get("label")
        if label and label != row["value"]:
            text.append("  ")
            text.append(Text(str(label)).plain, style="dim")
        if row.get("is_default"):
            text.append("  ")
            text.append("default", style="dim")
        description = row.get("description")
        if description:
            text.append("  ")
            text.append(Text(str(description)).plain, style="dim")
        if str(row["value"]) == self._current:
            text.append("  ")
            text.append("current", style="dim")
        return text


__all__ = ["EnumChoicePickerModal"]
