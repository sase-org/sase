"""Single-key spelling suggestion panel."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

_MAX_SUGGESTIONS = 9


class SpellcheckPanelModal(ModalScreen[str | None]):
    """Offer up to nine immediately applicable spelling corrections."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("enter", "apply_selected", "Apply"),
        ("j", "select_next", "Next"),
        ("k", "select_previous", "Previous"),
        ("ctrl+n", "select_next", "Next"),
        ("ctrl+p", "select_previous", "Previous"),
    ]

    def __init__(self, word: str, suggestions: tuple[str, ...]) -> None:
        super().__init__()
        self._word = word
        self._suggestions = suggestions[:_MAX_SUGGESTIONS]
        if not self._suggestions:
            raise ValueError("SpellcheckPanelModal requires at least one suggestion")
        self._selected_index = 0

    def compose(self) -> ComposeResult:
        with Container(id="spellcheck-container"):
            yield Static(self._build_title(), id="spellcheck-title")
            for index, _suggestion in enumerate(self._suggestions):
                yield Static(
                    self._build_row(index),
                    id=f"spellcheck-choice-{index}",
                    classes="spellcheck-choice-row",
                )
            yield Static(
                "1-9 apply | j/k move | Enter apply | Esc cancel",
                id="spellcheck-footer",
            )

    def on_mount(self) -> None:
        self._refresh_rows()

    def _build_title(self) -> Text:
        title = Text()
        title.append("≡", style="bold #FFD700")
        title.append(" ")
        title.append("SPELLING", style="bold #FF8787")
        title.append("  ")
        title.append(self._word, style="bold underline #FF8787")
        return title

    def _build_row(self, index: int) -> Text:
        selected = index == self._selected_index
        row = Text()
        row.append(
            ">" if selected else " ",
            style="bold #FF8787" if selected else "",
        )
        row.append(f" {index + 1} ", style="#FF8787")
        row.append(
            self._suggestions[index],
            style="bold white" if selected else "white",
        )
        return row

    def _refresh_rows(self) -> None:
        for index, _suggestion in enumerate(self._suggestions):
            row = self.query_one(f"#spellcheck-choice-{index}", Static)
            row.update(self._build_row(index))
            row.set_class(index == self._selected_index, "selected")

    def on_key(self, event: events.Key) -> None:
        """Handle choices directly and prevent keys reaching the prompt."""
        if event.key == "enter":
            self._stop_key(event)
            self.action_apply_selected()
        elif event.key in {"escape", "q"}:
            self._stop_key(event)
            self.action_cancel()
        elif event.key in {"j", "ctrl+n"}:
            self._stop_key(event)
            self.action_select_next()
        elif event.key in {"k", "ctrl+p"}:
            self._stop_key(event)
            self.action_select_previous()
        elif event.key.isdigit() and event.key != "0":
            self._stop_key(event)
            index = int(event.key) - 1
            if index < len(self._suggestions):
                self.dismiss(self._suggestions[index])
        elif event.character and event.character.isprintable():
            self._stop_key(event)

    @staticmethod
    def _stop_key(event: events.Key) -> None:
        event.prevent_default()
        event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_apply_selected(self) -> None:
        self.dismiss(self._suggestions[self._selected_index])

    def action_select_next(self) -> None:
        self._select_relative(1)

    def action_select_previous(self) -> None:
        self._select_relative(-1)

    def _select_relative(self, offset: int) -> None:
        self._selected_index = (self._selected_index + offset) % len(self._suggestions)
        self._refresh_rows()


__all__ = ["SpellcheckPanelModal"]
