"""Single-key spelling suggestion panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.core.word_lookup import MISSPELLING_COLOR

_MAX_SUGGESTIONS = 9


@dataclass(frozen=True, slots=True)
class SpellcheckChoice:
    """The user's choice from the spelling suggestion panel."""

    action: Literal["apply", "accept", "dictionary"]
    suggestion: str = ""


class SpellcheckPanelModal(ModalScreen[SpellcheckChoice | None]):
    """Offer up to nine immediately applicable spelling corrections.

    A word with no suggestions still opens the panel -- with a dim
    ``no suggestions`` row instead of choices -- so ``a`` can accept it. That
    matters most for proper nouns, which ``aspell`` rarely has ideas about.

    Two escape hatches leave a word alone, at different scopes: ``a`` accepts
    the word for SASE only, recorded in ``prompt_misspellings.json`` and
    reversible by editing that file; ``aspell`` itself still rejects the word
    everywhere else. ``d`` adds the word to the user's ``aspell`` personal
    dictionary, so every ``aspell`` consumer on the machine accepts it from
    then on; that add is verified in a fresh ``aspell`` process before the
    squiggle clears, and reversible by editing the personal dictionary file.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("enter", "apply_selected", "Apply"),
        ("j", "select_next", "Next"),
        ("k", "select_previous", "Previous"),
        ("ctrl+n", "select_next", "Next"),
        ("ctrl+p", "select_previous", "Previous"),
        ("a", "accept", "Accept"),
        ("d", "add_to_dictionary", "Dictionary"),
    ]

    def __init__(self, word: str, suggestions: tuple[str, ...]) -> None:
        super().__init__()
        self._word = word
        self._suggestions = suggestions[:_MAX_SUGGESTIONS]
        self._selected_index = 0

    def compose(self) -> ComposeResult:
        with Container(id="spellcheck-container"):
            yield Static(self._build_title(), id="spellcheck-title")
            if self._suggestions:
                for index, _suggestion in enumerate(self._suggestions):
                    yield Static(
                        self._build_row(index),
                        id=f"spellcheck-choice-{index}",
                        classes="spellcheck-choice-row",
                    )
            else:
                yield Static(
                    "no suggestions",
                    id="spellcheck-empty-row",
                    classes="spellcheck-empty-row",
                )
            yield Static(self._build_footer(), id="spellcheck-footer")

    def on_mount(self) -> None:
        self._refresh_rows()

    def _build_footer(self) -> str:
        second_line = "a accept | d add to aspell | Esc cancel"
        if not self._suggestions:
            return second_line
        return f"1-9 apply | j/k move | Enter apply\n{second_line}"

    def _build_title(self) -> Text:
        title = Text()
        title.append("≡", style="bold #FFD700")
        title.append(" ")
        title.append("SPELLING", style=f"bold {MISSPELLING_COLOR}")
        title.append("  ")
        title.append(self._word, style=f"bold underline {MISSPELLING_COLOR}")
        return title

    def _build_row(self, index: int) -> Text:
        selected = index == self._selected_index
        row = Text()
        row.append(
            ">" if selected else " ",
            style=f"bold {MISSPELLING_COLOR}" if selected else "",
        )
        row.append(f" {index + 1} ", style=MISSPELLING_COLOR)
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
        elif event.key == "a":
            self._stop_key(event)
            self.action_accept()
        elif event.key == "d":
            self._stop_key(event)
            self.action_add_to_dictionary()
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
                self.dismiss(
                    SpellcheckChoice(
                        action="apply", suggestion=self._suggestions[index]
                    )
                )
        elif event.character and event.character.isprintable():
            self._stop_key(event)

    @staticmethod
    def _stop_key(event: events.Key) -> None:
        event.prevent_default()
        event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_accept(self) -> None:
        self.dismiss(SpellcheckChoice(action="accept"))

    def action_add_to_dictionary(self) -> None:
        self.dismiss(SpellcheckChoice(action="dictionary"))

    def action_apply_selected(self) -> None:
        if not self._suggestions:
            return
        self.dismiss(
            SpellcheckChoice(
                action="apply",
                suggestion=self._suggestions[self._selected_index],
            )
        )

    def action_select_next(self) -> None:
        self._select_relative(1)

    def action_select_previous(self) -> None:
        self._select_relative(-1)

    def _select_relative(self, offset: int) -> None:
        if not self._suggestions:
            return
        self._selected_index = (self._selected_index + offset) % len(self._suggestions)
        self._refresh_rows()


__all__ = ["SpellcheckChoice", "SpellcheckPanelModal"]
