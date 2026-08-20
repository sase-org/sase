"""Types and errors for the memory-note mutation engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.memory.notes import MemoryNoteType

MemoryScopeKind = Literal["project", "home"]
MemoryDraftField = Literal["stem", "type", "parent", "description"]


@dataclass(frozen=True, slots=True)
class MemoryNoteDraft:
    """A normalized memory-note draft that passed structural checks."""

    stem: str
    relative_path: str
    note_type: MemoryNoteType
    parent: str
    description: str | None


@dataclass(frozen=True, slots=True)
class MemoryDraftValidation:
    """Per-field diagnostics for a memory-note draft.

    ``by_field`` only contains keys that have at least one message so a form
    can render errors inline. ``draft`` is set when stem/type/parent parsed
    far enough to name the candidate note, even if other fields still fail.
    """

    draft: MemoryNoteDraft | None
    by_field: Mapping[MemoryDraftField, tuple[str, ...]]

    def __bool__(self) -> bool:
        return not self.by_field and self.draft is not None


@dataclass(frozen=True, slots=True)
class MemoryMutationOutcome:
    """Result of a successful memory-note create, update, or delete."""

    scope_key: str
    content_root: Path
    relative_path: str
    stem: str
    type: MemoryNoteType
    parent: str
    description: str | None
    backup_path: Path | None = None


class MemoryMutationError(RuntimeError):
    """Raised when a memory-note mutation cannot be applied."""


class MemoryValidationError(MemoryMutationError):
    """Raised when a draft fails field validation."""

    def __init__(self, validation: MemoryDraftValidation) -> None:
        self.validation = validation
        parts = [
            f"{field}: {message}"
            for field, messages in validation.by_field.items()
            for message in messages
        ]
        super().__init__("; ".join(parts) or "memory note draft is invalid")


class MemoryConflictError(MemoryMutationError):
    """Raised when the note changed between preview and write."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(
            f"memory note changed after preview: {path}; reload and retry the edit"
        )


class MemoryGeneratedNoteError(MemoryMutationError):
    """Raised when a generated memory note is the mutation target."""

    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        super().__init__(f"generated memory note is read-only: {relative_path}")


__all__ = [
    "MemoryConflictError",
    "MemoryDraftField",
    "MemoryDraftValidation",
    "MemoryGeneratedNoteError",
    "MemoryMutationError",
    "MemoryMutationOutcome",
    "MemoryNoteDraft",
    "MemoryScopeKind",
    "MemoryValidationError",
]
