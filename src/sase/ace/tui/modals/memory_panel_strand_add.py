"""Add form for a new memory-web strand.

Mirrors :mod:`sase.ace.tui.modals.memory_panel_add`'s shape:
``validate_memory_strand_draft()`` runs on the same 150ms debounce as the
flat-note form, and submit is refused while any blocking diagnostic stands.
Editing an existing strand stays out of scope -- this modal only ever
creates a brand-new strand file. The write itself stays on the panel.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Input, Static, TextArea

from sase.memory.web.frontmatter import slug_to_keyword
from sase.memory.web.models import MemoryWeb
from sase.memory.web.mutation_models import MemoryStrandDraftValidation
from sase.memory.web.mutation_validate import validate_memory_strand_draft

_VALIDATE_DELAY_S = 0.15

_DEFERRED_UNTIL_SUBMIT = frozenset(
    {
        "memory strand slug is required",
        "memory strand body is required",
    }
)


@dataclass(frozen=True, slots=True)
class MemoryStrandFormDraft:
    """Validated values the panel writes through the shared mutation engine."""

    web_slug: str
    slug: str
    keyword: str
    aliases: tuple[str, ...]
    summary: str | None
    body: str


@dataclass(frozen=True, slots=True)
class _MemoryStrandFormFieldErrors:
    """Blocking diagnostics grouped under the field they name."""

    slug: tuple[str, ...] = ()
    keyword: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    summary: tuple[str, ...] = ()
    body: tuple[str, ...] = ()

    @property
    def blocking(self) -> bool:
        return bool(
            self.slug or self.keyword or self.aliases or self.summary or self.body
        )


def _parse_alias_input(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _errors_from_validation(
    validation: MemoryStrandDraftValidation, body_errors: tuple[str, ...]
) -> _MemoryStrandFormFieldErrors:
    by_field = validation.by_field
    return _MemoryStrandFormFieldErrors(
        slug=tuple(by_field.get("slug", ())),
        keyword=tuple(by_field.get("keyword", ())),
        aliases=tuple(by_field.get("aliases", ())),
        summary=tuple(by_field.get("summary", ())),
        body=body_errors,
    )


class MemoryStrandFormModal(ModalScreen[MemoryStrandFormDraft | None]):
    """Collect slug, keyword, aliases, summary, and body for a new strand."""

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
        web: MemoryWeb,
        scope_display_name: str = "",
        accent: str = "#87D7FF",
    ) -> None:
        super().__init__()
        self._web = web
        self._scope_display_name = scope_display_name
        self._accent = accent
        self._submitted = False
        self._keyword_touched = False
        self._validate_timer: Timer | None = None
        self._errors = _MemoryStrandFormFieldErrors()

    def compose(self) -> ComposeResult:
        with Container(id="memory-strand-form-container"):
            yield Static(self._title_text(), id="memory-strand-form-title")
            with Vertical(id="memory-strand-form-fields"):
                yield Static("Slug", classes="memory-strand-form-label")
                yield Input(
                    placeholder="Required, flat name",
                    id="memory-strand-form-slug",
                )
                yield Static(
                    "",
                    id="memory-strand-form-slug-error",
                    classes="memory-strand-form-error",
                )
                yield Static("Keyword", classes="memory-strand-form-label")
                yield Input(
                    placeholder="Display term (defaults from slug)",
                    id="memory-strand-form-keyword",
                )
                yield Static(
                    "",
                    id="memory-strand-form-keyword-error",
                    classes="memory-strand-form-error",
                )
                yield Static("Aliases", classes="memory-strand-form-label")
                yield Input(
                    placeholder="Comma-separated, optional",
                    id="memory-strand-form-aliases",
                )
                yield Static(
                    "",
                    id="memory-strand-form-aliases-error",
                    classes="memory-strand-form-error",
                )
                yield Static("Summary", classes="memory-strand-form-label")
                yield Input(
                    placeholder="Optional one-line summary",
                    id="memory-strand-form-summary",
                )
                yield Static(
                    "",
                    id="memory-strand-form-summary-error",
                    classes="memory-strand-form-error",
                )
                yield Static("Body", classes="memory-strand-form-label")
                yield TextArea(id="memory-strand-form-body")
                yield Static(
                    "",
                    id="memory-strand-form-body-error",
                    classes="memory-strand-form-error",
                )
            yield Static(
                "ctrl+s submit  ·  tab field  ·  esc cancel",
                id="memory-strand-form-hints",
            )

    def on_mount(self) -> None:
        self.query_one("#memory-strand-form-slug", Input).focus()

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
        validation, _body_errors = self._run_validation()
        draft = validation.draft
        if draft is None:
            return
        body = self.query_one("#memory-strand-form-body", TextArea).text
        self.dismiss(
            MemoryStrandFormDraft(
                web_slug=self._web.slug,
                slug=draft.slug,
                keyword=draft.keyword,
                aliases=draft.aliases,
                summary=draft.summary,
                body=body,
            )
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "memory-strand-form-slug":
            self._maybe_autofill_keyword()
            self._schedule_validate()
        elif event.input.id == "memory-strand-form-keyword":
            self._keyword_touched = bool(event.input.value.strip())
            self._schedule_validate()
        elif event.input.id in {
            "memory-strand-form-aliases",
            "memory-strand-form-summary",
        }:
            self._schedule_validate()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "memory-strand-form-slug":
            self.focus_next()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "memory-strand-form-body":
            self._schedule_validate()

    def _title_text(self) -> Text:
        text = Text()
        text.append("Add memory strand", style=f"bold {self._accent}")
        text.append("  ·  ", style="dim")
        text.append(self._web.slug, style="bold")
        if self._scope_display_name:
            text.append("  ·  ", style="dim")
            text.append(self._scope_display_name, style="bold")
        return text

    def _maybe_autofill_keyword(self) -> None:
        if not self.is_mounted or self._keyword_touched:
            return
        slug = self.query_one("#memory-strand-form-slug", Input).value
        keyword_input = self.query_one("#memory-strand-form-keyword", Input)
        keyword_input.value = slug_to_keyword(slug) if slug.strip() else ""

    def _schedule_validate(self) -> None:
        self._cancel_validate_timer()
        self._validate_timer = self.set_timer(_VALIDATE_DELAY_S, self._validate_now)

    def _cancel_validate_timer(self) -> None:
        if self._validate_timer is not None:
            self._validate_timer.stop()
            self._validate_timer = None

    def _run_validation(self) -> tuple[MemoryStrandDraftValidation, tuple[str, ...]]:
        slug = self.query_one("#memory-strand-form-slug", Input).value
        keyword = self.query_one("#memory-strand-form-keyword", Input).value.strip()
        aliases = _parse_alias_input(
            self.query_one("#memory-strand-form-aliases", Input).value
        )
        summary = self.query_one("#memory-strand-form-summary", Input).value.strip()
        body = self.query_one("#memory-strand-form-body", TextArea).text
        validation = validate_memory_strand_draft(
            web=self._web,
            slug=slug,
            keyword=keyword or None,
            aliases=aliases,
            summary=summary or None,
        )
        body_errors = () if body.strip() else ("memory strand body is required",)
        return validation, body_errors

    def _validate_now(self) -> _MemoryStrandFormFieldErrors:
        self._validate_timer = None
        if not self.is_mounted:
            return self._errors
        validation, body_errors = self._run_validation()
        errors = _errors_from_validation(validation, body_errors)
        self._errors = errors
        self._render_errors(self._visible_errors(errors))
        return errors

    def _visible_errors(
        self, errors: _MemoryStrandFormFieldErrors
    ) -> _MemoryStrandFormFieldErrors:
        if self._submitted:
            return errors
        return _MemoryStrandFormFieldErrors(
            slug=_live_messages(errors.slug),
            keyword=_live_messages(errors.keyword),
            aliases=errors.aliases,
            summary=errors.summary,
            body=_live_messages(errors.body),
        )

    def _render_errors(self, errors: _MemoryStrandFormFieldErrors) -> None:
        self.query_one("#memory-strand-form-slug-error", Static).update(
            _error_text(errors.slug)
        )
        self.query_one("#memory-strand-form-keyword-error", Static).update(
            _error_text(errors.keyword)
        )
        self.query_one("#memory-strand-form-aliases-error", Static).update(
            _error_text(errors.aliases)
        )
        self.query_one("#memory-strand-form-summary-error", Static).update(
            _error_text(errors.summary)
        )
        self.query_one("#memory-strand-form-body-error", Static).update(
            _error_text(errors.body)
        )


def _live_messages(messages: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        message for message in messages if message not in _DEFERRED_UNTIL_SUBMIT
    )


def _error_text(messages: tuple[str, ...]) -> str:
    return "\n".join(messages)


__all__ = [
    "MemoryStrandFormDraft",
    "MemoryStrandFormModal",
]
