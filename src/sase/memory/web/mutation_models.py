"""Types and errors for the memory-web strand mutation engine.

Digest conflicts reuse :class:`sase.memory.mutation_models.MemoryConflictError`
directly (a strand conflict is the same "changed after preview" shape as a flat
note conflict), but a strand draft's fields (``slug``/``keyword``/``aliases``/
``summary``/``metadata``) don't line up with a note draft's
(``stem``/``type``/``parent``/``description``), so validation gets its own
draft, per-field diagnostics, and error types here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

MemoryStrandDraftField = Literal["slug", "keyword", "aliases", "summary", "metadata"]


@dataclass(frozen=True, slots=True)
class MemoryStrandDraft:
    """A normalized memory-web strand draft that passed structural checks."""

    slug: str
    relative_path: str
    keyword: str
    aliases: tuple[str, ...]
    summary: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MemoryStrandDraftValidation:
    """Per-field diagnostics for a memory-web strand draft.

    ``by_field`` only contains keys that have at least one message so a form
    can render errors inline. ``draft`` is set when slug/keyword parsed far
    enough to name the candidate strand, even if other fields still fail.
    """

    draft: MemoryStrandDraft | None
    by_field: Mapping[MemoryStrandDraftField, tuple[str, ...]]

    def __bool__(self) -> bool:
        return not self.by_field and self.draft is not None


@dataclass(frozen=True, slots=True)
class MemoryStrandMutationOutcome:
    """Result of a successful memory-web strand create or delete."""

    scope_key: str
    content_root: Path
    web_slug: str
    relative_path: str
    slug: str
    keyword: str
    aliases: tuple[str, ...]
    summary: str | None
    metadata: dict[str, Any]
    backup_path: Path | None = None


class MemoryStrandMutationError(RuntimeError):
    """Raised when a memory-web strand mutation cannot be applied."""


class MemoryStrandValidationError(MemoryStrandMutationError):
    """Raised when a strand draft fails field validation."""

    def __init__(self, validation: MemoryStrandDraftValidation) -> None:
        self.validation = validation
        parts = [
            f"{field}: {message}"
            for field, messages in validation.by_field.items()
            for message in messages
        ]
        super().__init__("; ".join(parts) or "memory strand draft is invalid")


__all__ = [
    "MemoryStrandDraft",
    "MemoryStrandDraftField",
    "MemoryStrandDraftValidation",
    "MemoryStrandMutationError",
    "MemoryStrandMutationOutcome",
    "MemoryStrandValidationError",
]
