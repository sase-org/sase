"""Add-term form for the Glossary panel.

Validation is pure computation over the already-loaded entry set: the Rust
validator runs inline on a debounce, and submit is refused while any
error-severity diagnostic stands. The write itself stays on the panel.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Input, Static, TextArea

from sase.core.glossary_facade import (
    GlossaryDiagnostic,
    GlossaryEntry,
    GlossaryInputEntry,
    validate_glossary_entries,
)
from sase.glossary.resolution import normalize_glossary_reference

_VALIDATE_DELAY_S = 0.15
_AddField = Literal["term", "aliases", "definition"]


@dataclass(frozen=True, slots=True)
class GlossaryAddDraft:
    """Validated values the panel writes through the shared mutation engine."""

    term: str
    aliases: tuple[str, ...]
    definition: str


@dataclass(frozen=True, slots=True)
class _GlossaryAddFieldErrors:
    """Blocking diagnostics grouped under the field they name."""

    term: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    definition: tuple[str, ...] = ()

    @property
    def blocking(self) -> bool:
        return bool(self.term or self.aliases or self.definition)


def _parse_glossary_alias_field(raw: str) -> tuple[str, ...]:
    """Split a comma-separated aliases field into stripped non-empty tokens."""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _validate_glossary_add_draft(
    existing: Sequence[GlossaryEntry],
    *,
    term: str,
    aliases_text: str,
    definition: str,
) -> _GlossaryAddFieldErrors:
    """Validate a candidate add against local rules and the Rust entry set."""
    term_errors: list[str] = []
    alias_errors: list[str] = []
    definition_errors: list[str] = []

    if "\n" in term or "\r" in term:
        term_errors.append("glossary term must be a single-line string")
    cleaned_term = term.strip()
    if not cleaned_term:
        term_errors.append("glossary term must be a nonblank string")
    elif not term_errors and not normalize_glossary_reference(cleaned_term):
        term_errors.append("glossary term must contain more than separators")

    cleaned_definition = definition.strip()
    if not cleaned_definition:
        definition_errors.append("glossary definition must be a nonblank string")

    aliases: list[str] = []
    for alias in _parse_glossary_alias_field(aliases_text):
        if "\n" in alias or "\r" in alias:
            alias_errors.append("glossary alias must be a single-line string")
            break
        aliases.append(alias)

    if term_errors or alias_errors or definition_errors:
        return _GlossaryAddFieldErrors(
            term=tuple(term_errors),
            aliases=tuple(alias_errors),
            definition=tuple(definition_errors),
        )

    candidate = (
        *(
            GlossaryInputEntry(
                term=entry.term,
                definition=entry.definition,
                aliases=entry.configured_aliases,
            )
            for entry in existing
        ),
        GlossaryInputEntry(
            term=cleaned_term,
            definition=cleaned_definition,
            aliases=tuple(aliases),
        ),
    )
    for item in validate_glossary_entries(candidate):
        if item.severity != "error":
            continue
        message = f"{item.code}: {item.message}"
        field = _field_for_glossary_diagnostic(
            item, cleaned_term, aliases=tuple(aliases)
        )
        if field == "aliases":
            alias_errors.append(message)
        elif field == "definition":
            definition_errors.append(message)
        else:
            term_errors.append(message)
    return _GlossaryAddFieldErrors(
        term=tuple(term_errors),
        aliases=tuple(alias_errors),
        definition=tuple(definition_errors),
    )


def _field_for_glossary_diagnostic(
    item: GlossaryDiagnostic,
    term: str,
    *,
    aliases: Sequence[str] = (),
) -> _AddField:
    """Map a Rust diagnostic path onto the add-form field it names.

    A duplicate term is reported as ``alias_conflict`` on
    ``glossary.<term>.aliases[0]`` because the term is also an implicit
    alias. When the user did not type any aliases, surface that on Term.
    """
    path = item.path or ""
    remainder = path[len("glossary.") :] if path.startswith("glossary.") else path
    name, _sep, rest = remainder.partition(".")
    if rest.startswith("aliases") or ".aliases" in path or path.endswith("aliases"):
        if not aliases and name.casefold() == term.casefold():
            return "term"
        return "aliases"
    if rest.startswith("definition") or ".definition" in path:
        return "definition"
    return "term"


class GlossaryTermAddModal(ModalScreen[GlossaryAddDraft | None]):
    """Collect a new glossary term, optional aliases, and a definition."""

    AUTO_FOCUS = None
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
        Binding("ctrl+s", "submit", "Submit", show=False, priority=True),
        Binding("tab", "focus_next", "Next field", show=False, priority=True),
        Binding(
            "shift+tab",
            "focus_previous",
            "Previous field",
            show=False,
            priority=True,
        ),
    ]

    def __init__(
        self,
        *,
        existing_entries: Sequence[GlossaryEntry] = (),
        project_display_name: str = "",
        accent: str = "#87D7FF",
    ) -> None:
        super().__init__()
        self._existing = tuple(existing_entries)
        self._project_display_name = project_display_name
        self._accent = accent
        self._submitted = False
        self._validate_timer: Timer | None = None
        self._errors = _GlossaryAddFieldErrors()

    def compose(self) -> ComposeResult:
        with Container(id="glossary-add-container"):
            yield Static(self._title_text(), id="glossary-add-title")
            with Vertical(id="glossary-add-fields"):
                yield Static("Term", classes="glossary-add-label")
                yield Input(placeholder="Required", id="glossary-add-term")
                yield Static(
                    "",
                    id="glossary-add-term-error",
                    classes="glossary-add-error",
                )
                yield Static("Aliases", classes="glossary-add-label")
                yield Input(
                    placeholder="comma-separated, optional",
                    id="glossary-add-aliases",
                )
                yield Static(
                    "",
                    id="glossary-add-aliases-error",
                    classes="glossary-add-error",
                )
                yield Static("Definition", classes="glossary-add-label")
                yield TextArea(id="glossary-add-definition")
                yield Static(
                    "",
                    id="glossary-add-definition-error",
                    classes="glossary-add-error",
                )
            yield Static(
                "ctrl+s submit  ·  tab field  ·  esc cancel",
                id="glossary-add-hints",
            )

    def on_mount(self) -> None:
        self.query_one("#glossary-add-term", Input).focus()

    def on_unmount(self) -> None:
        self._cancel_validate_timer()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self._submitted = True
        self._cancel_validate_timer()
        errors = self._validate_now()
        if errors.blocking:
            return
        term = self.query_one("#glossary-add-term", Input).value.strip()
        definition = self.query_one("#glossary-add-definition", TextArea).text.strip()
        aliases = _parse_glossary_alias_field(
            self.query_one("#glossary-add-aliases", Input).value
        )
        self.dismiss(
            GlossaryAddDraft(term=term, aliases=aliases, definition=definition)
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in {"glossary-add-term", "glossary-add-aliases"}:
            self._schedule_validate()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id in {"glossary-add-term", "glossary-add-aliases"}:
            self.focus_next()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "glossary-add-definition":
            self._schedule_validate()

    def _title_text(self) -> Text:
        text = Text()
        text.append("Add glossary term", style=f"bold {self._accent}")
        if self._project_display_name:
            text.append("  ·  ", style="dim")
            text.append(self._project_display_name, style="bold")
        return text

    def _schedule_validate(self) -> None:
        self._cancel_validate_timer()
        self._validate_timer = self.set_timer(_VALIDATE_DELAY_S, self._validate_now)

    def _cancel_validate_timer(self) -> None:
        if self._validate_timer is not None:
            self._validate_timer.stop()
            self._validate_timer = None

    def _validate_now(self) -> _GlossaryAddFieldErrors:
        self._validate_timer = None
        if not self.is_mounted:
            return self._errors
        errors = _validate_glossary_add_draft(
            self._existing,
            term=self.query_one("#glossary-add-term", Input).value,
            aliases_text=self.query_one("#glossary-add-aliases", Input).value,
            definition=self.query_one("#glossary-add-definition", TextArea).text,
        )
        self._errors = errors
        self._render_errors(self._visible_errors(errors))
        return errors

    def _visible_errors(
        self, errors: _GlossaryAddFieldErrors
    ) -> _GlossaryAddFieldErrors:
        if self._submitted:
            return errors
        return _GlossaryAddFieldErrors(
            term=_live_messages(errors.term),
            aliases=_live_messages(errors.aliases),
            definition=_live_messages(errors.definition),
        )

    def _render_errors(self, errors: _GlossaryAddFieldErrors) -> None:
        self.query_one("#glossary-add-term-error", Static).update(
            _error_text(errors.term)
        )
        self.query_one("#glossary-add-aliases-error", Static).update(
            _error_text(errors.aliases)
        )
        self.query_one("#glossary-add-definition-error", Static).update(
            _error_text(errors.definition)
        )


def _live_messages(messages: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(message for message in messages if "nonblank" not in message)


def _error_text(messages: tuple[str, ...]) -> str:
    return "\n".join(messages)


__all__ = [
    "GlossaryAddDraft",
    "GlossaryTermAddModal",
]
