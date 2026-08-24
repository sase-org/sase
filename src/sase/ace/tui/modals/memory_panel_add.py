"""Add/edit form for the Memory panel.

Validation is pure computation over the already-loaded note set:
``validate_memory_note_draft()`` runs on a brief debounce, and submit is
refused while any blocking diagnostic stands. The write itself stays on
the panel.
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
from textual.widgets import Input, Select, Static, TextArea

from sase.memory.mutation import (
    MemoryDraftValidation,
    MemoryNoteDraft,
    memory_note_relative_path_for_stem,
    validate_memory_note_draft,
)
from sase.memory.notes import AGENTS_PARENT, MemoryNote

_VALIDATE_DELAY_S = 0.15
_FormMode = Literal["add", "edit"]
_FormField = Literal["stem", "type", "parent", "description"]

_DEFERRED_UNTIL_SUBMIT = frozenset(
    {
        "memory note stem is required",
        "reference memory notes require a description",
    }
)


@dataclass(frozen=True, slots=True)
class MemoryNoteFormDraft:
    """Validated values the panel writes through the shared mutation engine."""

    stem: str
    note_type: str
    parent: str
    description: str


@dataclass(frozen=True, slots=True)
class _MemoryFormFieldErrors:
    """Blocking diagnostics grouped under the field they name."""

    stem: tuple[str, ...] = ()
    type: tuple[str, ...] = ()
    parent: tuple[str, ...] = ()
    description: tuple[str, ...] = ()

    @property
    def blocking(self) -> bool:
        return bool(self.stem or self.type or self.parent or self.description)


def _memory_parent_options(
    notes: Sequence[MemoryNote],
    *,
    current_relative_path: str | None = None,
    current_parent: str = AGENTS_PARENT,
) -> tuple[tuple[str, str], ...]:
    """Return ``(label, value)`` parent choices for the add/edit form.

    ``AGENTS.md`` is always first, then every reference note except the note
    being edited. An orphaned current parent is appended so edit mode does
    not silently rewrite it.
    """
    options: list[tuple[str, str]] = [("AGENTS.md", AGENTS_PARENT)]
    seen = {AGENTS_PARENT}
    for note in notes:
        if note.type != "reference":
            continue
        if note.relative_path == current_relative_path:
            continue
        label = f"{note.path.stem} ({note.relative_path})"
        options.append((label, note.relative_path))
        seen.add(note.relative_path)
    if current_parent and current_parent not in seen:
        options.append((current_parent, current_parent))
    return tuple(options)


def _memory_note_path_preview(stem: str) -> str:
    """Return the canonical relative path for a flat stem, or ``""``."""
    cleaned = stem.strip()
    if cleaned.lower().endswith(".md"):
        cleaned = cleaned[:-3]
    if not cleaned or "/" in cleaned or "\\" in cleaned:
        return ""
    return memory_note_relative_path_for_stem(cleaned)


def _errors_from_validation(
    validation: MemoryDraftValidation,
) -> _MemoryFormFieldErrors:
    by_field = validation.by_field
    return _MemoryFormFieldErrors(
        stem=tuple(by_field.get("stem", ())),
        type=tuple(by_field.get("type", ())),
        parent=tuple(by_field.get("parent", ())),
        description=tuple(by_field.get("description", ())),
    )


class MemoryNoteFormModal(ModalScreen[MemoryNoteFormDraft | None]):
    """Collect stem, tier, parent, and description for a create or edit."""

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
        mode: _FormMode = "add",
        existing_notes: Sequence[MemoryNote] = (),
        scope_display_name: str = "",
        include_project_memory: bool = True,
        initial_stem: str = "",
        initial_type: str = "reference",
        initial_parent: str = AGENTS_PARENT,
        initial_description: str = "",
        current_relative_path: str | None = None,
        accent: str = "#87D7FF",
    ) -> None:
        super().__init__()
        self._mode: _FormMode = mode
        self._existing = tuple(existing_notes)
        self._scope_display_name = scope_display_name
        self._include_project_memory = include_project_memory
        self._initial_stem = initial_stem
        self._initial_type = (
            initial_type if initial_type in {"core", "reference"} else "reference"
        )
        self._initial_parent = initial_parent or AGENTS_PARENT
        self._initial_description = initial_description
        self._current_relative_path = current_relative_path
        self._accent = accent
        self._submitted = False
        self._validate_timer: Timer | None = None
        self._errors = _MemoryFormFieldErrors()

    def compose(self) -> ComposeResult:
        parent_options = _memory_parent_options(
            self._existing,
            current_relative_path=self._current_relative_path,
            current_parent=self._initial_parent,
        )
        with Container(id="memory-note-form-container"):
            yield Static(self._title_text(), id="memory-note-form-title")
            with Vertical(id="memory-note-form-fields"):
                yield Static("Stem", classes="memory-note-form-label")
                yield Input(
                    value=self._initial_stem,
                    placeholder="Required, flat name",
                    id="memory-note-form-stem",
                    disabled=self._mode == "edit",
                )
                yield Static(
                    self._initial_path_preview(),
                    id="memory-note-form-path",
                    classes="memory-note-form-path",
                )
                yield Static(
                    "",
                    id="memory-note-form-stem-error",
                    classes="memory-note-form-error",
                )
                yield Static("Tier", classes="memory-note-form-label")
                yield Select(
                    (
                        ("core — Tier 1, always loaded", "core"),
                        ("reference — Tier 2", "reference"),
                    ),
                    value=self._initial_type,
                    allow_blank=False,
                    id="memory-note-form-type",
                )
                yield Static(
                    "",
                    id="memory-note-form-type-error",
                    classes="memory-note-form-error",
                )
                yield Static("Parent", classes="memory-note-form-label")
                yield Select(
                    parent_options,
                    value=self._parent_select_value(parent_options),
                    allow_blank=False,
                    id="memory-note-form-parent",
                    disabled=self._initial_type == "core",
                )
                yield Static(
                    "",
                    id="memory-note-form-parent-error",
                    classes="memory-note-form-error",
                )
                yield Static("Description", classes="memory-note-form-label")
                yield TextArea(
                    self._initial_description,
                    id="memory-note-form-description",
                )
                yield Static(
                    "",
                    id="memory-note-form-description-error",
                    classes="memory-note-form-error",
                )
            yield Static(
                "ctrl+s submit  ·  tab field  ·  esc cancel",
                id="memory-note-form-hints",
            )

    def on_mount(self) -> None:
        if self._mode == "edit":
            self.query_one("#memory-note-form-type", Select).focus()
        else:
            self.query_one("#memory-note-form-stem", Input).focus()

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
        validation = self._validate_draft()
        draft: MemoryNoteDraft | None = validation.draft
        if draft is None:
            return
        self.dismiss(
            MemoryNoteFormDraft(
                stem=draft.stem,
                note_type=draft.note_type,
                parent=draft.parent,
                description=draft.description or "",
            )
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "memory-note-form-stem":
            self._update_path_preview()
            self._schedule_validate()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "memory-note-form-stem":
            self.focus_next()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "memory-note-form-type":
            self._sync_parent_for_type()
        if event.select.id in {
            "memory-note-form-type",
            "memory-note-form-parent",
        }:
            self._schedule_validate()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "memory-note-form-description":
            self._schedule_validate()

    def _title_text(self) -> Text:
        title = "Edit memory note" if self._mode == "edit" else "Add memory note"
        text = Text()
        text.append(title, style=f"bold {self._accent}")
        if self._scope_display_name:
            text.append("  ·  ", style="dim")
            text.append(self._scope_display_name, style="bold")
        return text

    def _initial_path_preview(self) -> str:
        if self._current_relative_path:
            return self._current_relative_path
        return _memory_note_path_preview(self._initial_stem)

    def _parent_select_value(self, options: Sequence[tuple[str, str]]) -> str:
        values = {value for _label, value in options}
        if self._initial_parent in values:
            return self._initial_parent
        return AGENTS_PARENT

    def _update_path_preview(self) -> None:
        if not self.is_mounted or self._mode == "edit":
            return
        preview = _memory_note_path_preview(
            self.query_one("#memory-note-form-stem", Input).value
        )
        self.query_one("#memory-note-form-path", Static).update(preview)

    def _sync_parent_for_type(self) -> None:
        parent_select = self.query_one("#memory-note-form-parent", Select)
        if self._type_value() == "core":
            parent_select.value = AGENTS_PARENT
            parent_select.disabled = True
        else:
            parent_select.disabled = False

    def _type_value(self) -> str:
        value = self.query_one("#memory-note-form-type", Select).value
        if value is Select.BLANK:
            return ""
        return str(value)

    def _parent_value(self) -> str:
        value = self.query_one("#memory-note-form-parent", Select).value
        if value is Select.BLANK:
            return ""
        return str(value)

    def _schedule_validate(self) -> None:
        self._cancel_validate_timer()
        self._validate_timer = self.set_timer(_VALIDATE_DELAY_S, self._validate_now)

    def _cancel_validate_timer(self) -> None:
        if self._validate_timer is not None:
            self._validate_timer.stop()
            self._validate_timer = None

    def _validate_draft(self) -> MemoryDraftValidation:
        description = self.query_one(
            "#memory-note-form-description", TextArea
        ).text.strip()
        return validate_memory_note_draft(
            stem=self.query_one("#memory-note-form-stem", Input).value,
            note_type=self._type_value(),
            parent=self._parent_value(),
            description=description or None,
            existing_notes=self._existing,
            current_relative_path=self._current_relative_path,
            include_project_memory=self._include_project_memory,
        )

    def _validate_now(self) -> _MemoryFormFieldErrors:
        self._validate_timer = None
        if not self.is_mounted:
            return self._errors
        errors = _errors_from_validation(self._validate_draft())
        self._errors = errors
        self._render_errors(self._visible_errors(errors))
        return errors

    def _visible_errors(self, errors: _MemoryFormFieldErrors) -> _MemoryFormFieldErrors:
        if self._submitted:
            return errors
        return _MemoryFormFieldErrors(
            stem=_live_messages(errors.stem),
            type=_live_messages(errors.type),
            parent=_live_messages(errors.parent),
            description=_live_messages(errors.description),
        )

    def _render_errors(self, errors: _MemoryFormFieldErrors) -> None:
        self.query_one("#memory-note-form-stem-error", Static).update(
            _error_text(errors.stem)
        )
        self.query_one("#memory-note-form-type-error", Static).update(
            _error_text(errors.type)
        )
        self.query_one("#memory-note-form-parent-error", Static).update(
            _error_text(errors.parent)
        )
        self.query_one("#memory-note-form-description-error", Static).update(
            _error_text(errors.description)
        )


def _live_messages(messages: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        message for message in messages if message not in _DEFERRED_UNTIL_SUBMIT
    )


def _error_text(messages: tuple[str, ...]) -> str:
    return "\n".join(messages)


__all__ = [
    "MemoryNoteFormDraft",
    "MemoryNoteFormModal",
]
