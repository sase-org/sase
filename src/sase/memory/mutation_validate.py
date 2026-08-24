"""Pure validation for memory-note create and update drafts.

This module does not read or write the filesystem. Callers pass the scope's
already-loaded notes so a form can share them with the engine.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import re

from sase.main.init_memory.root_rendering import generated_memory_note_relative_paths
from sase.memory.mutation_models import (
    MemoryDraftField,
    MemoryDraftValidation,
    MemoryGeneratedNoteError,
    MemoryMutationError,
    MemoryNoteDraft,
)
from sase.memory.notes import (
    AGENTS_PARENT,
    MemoryNote,
    MemoryNoteType,
    apply_memory_frontmatter,
    normalize_memory_note_type,
    parse_memory_note_text,
)
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    canonical_memory_reference,
    memory_note_relative_path,
)

_STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_README_STEM = "readme"


def memory_note_relative_path_for_stem(stem: str) -> str:
    """Return the canonical root-relative path for a flat memory-note stem."""
    return (CANONICAL_MEMORY_RELATIVE_ROOT / f"{stem}.md").as_posix()


def validate_memory_note_draft(
    *,
    stem: str,
    note_type: str,
    parent: str,
    description: str | None,
    existing_notes: Sequence[MemoryNote] = (),
    current_relative_path: str | None = None,
    include_project_memory: bool = True,
) -> MemoryDraftValidation:
    """Return per-field diagnostics for a create or update draft.

    This function is pure: it does not read or write the filesystem. Callers
    pass the scope's already-loaded notes so the panel form can share it.
    """
    errors: dict[MemoryDraftField, list[str]] = {
        "stem": [],
        "type": [],
        "parent": [],
        "description": [],
    }
    parsed_stem, stem_errors = _parse_stem(stem)
    errors["stem"].extend(stem_errors)

    cleaned_type = note_type.strip()
    normalized_type = normalize_memory_note_type(cleaned_type)
    parsed_type: MemoryNoteType | None
    if normalized_type == "core":
        parsed_type = "core"
    elif normalized_type == "reference":
        parsed_type = "reference"
    else:
        parsed_type = None
        errors["type"].append("memory note type must be core or reference")

    parsed_parent, parent_parse_errors = _parse_parent(parent)
    errors["parent"].extend(parent_parse_errors)

    current_canonical = (
        _canonical_flat_note_path(current_relative_path)
        if current_relative_path is not None
        else None
    )
    relative_path: str | None = None
    if current_canonical is not None:
        relative_path = current_canonical
    elif parsed_stem is not None:
        relative_path = memory_note_relative_path_for_stem(parsed_stem)

    if relative_path is not None and _is_generated_relative_path(
        relative_path, include_project_memory=include_project_memory
    ):
        errors["stem"].append(f"generated memory note is read-only: {relative_path}")

    notes_by_path = {note.relative_path: note for note in existing_notes}
    if (
        relative_path is not None
        and relative_path in notes_by_path
        and relative_path != current_canonical
    ):
        errors["stem"].append(f"a memory note already exists at {relative_path}")

    parsed_description = _normalize_description(description)
    if parsed_type == "reference" and parsed_description is None:
        errors["description"].append("reference memory notes require a description")

    if parsed_type == "core" and parsed_parent is not None:
        if parsed_parent != AGENTS_PARENT:
            errors["parent"].append("core memory notes must parent to AGENTS.md")

    if (
        parsed_type == "reference"
        and parsed_parent is not None
        and parsed_parent != AGENTS_PARENT
        and relative_path is not None
    ):
        errors["parent"].extend(
            _parent_legality_errors(
                note_relative_path=relative_path,
                parent=parsed_parent,
                notes_by_path=notes_by_path,
            )
        )

    if current_canonical is not None and parsed_type is not None:
        children = children_of_memory_note(existing_notes, current_canonical)
        if children and parsed_type != "reference":
            named = ", ".join(child.relative_path for child in children)
            errors["type"].append(
                f"cannot change type to core while children exist ({named})"
            )

    draft: MemoryNoteDraft | None = None
    if (
        parsed_stem is not None
        and parsed_type is not None
        and parsed_parent is not None
    ):
        draft = MemoryNoteDraft(
            stem=Path(
                relative_path or memory_note_relative_path_for_stem(parsed_stem)
            ).stem,
            relative_path=relative_path
            or memory_note_relative_path_for_stem(parsed_stem),
            note_type=parsed_type,
            parent=parsed_parent,
            description=parsed_description,
        )

    by_field = {
        field: tuple(messages) for field, messages in errors.items() if messages
    }
    return MemoryDraftValidation(draft=draft, by_field=by_field)


def raise_if_generated_memory_stem(stem: str, include_project_memory: bool) -> None:
    """Raise when a create stem names a generated memory note."""
    parsed_stem, _stem_errors = _parse_stem(stem)
    if parsed_stem is not None:
        raise_if_generated_memory_note(
            memory_note_relative_path_for_stem(parsed_stem),
            include_project_memory,
        )


def raise_if_generated_memory_note(
    relative_path: str, include_project_memory: bool
) -> None:
    """Raise when ``relative_path`` is a generated memory note."""
    if _is_generated_relative_path(
        relative_path, include_project_memory=include_project_memory
    ):
        raise MemoryGeneratedNoteError(relative_path)


def require_flat_memory_note_path(raw: str) -> str:
    """Return the canonical flat note path, or raise if ``raw`` is not one."""
    canonical = _canonical_flat_note_path(raw)
    if canonical is None:
        raise MemoryMutationError(
            f"memory note path is not a flat note inside the memory root: {raw}"
        )
    return canonical


def children_of_memory_note(
    notes: Sequence[MemoryNote], relative_path: str
) -> tuple[MemoryNote, ...]:
    """Return notes that parent to ``relative_path``, sorted by path."""
    children = [note for note in notes if note.parent == relative_path]
    return tuple(sorted(children, key=lambda note: note.relative_path))


def _is_generated_relative_path(
    relative_path: str, *, include_project_memory: bool
) -> bool:
    generated = {
        path.as_posix()
        for path in generated_memory_note_relative_paths(
            include_project_memory=include_project_memory
        )
    }
    return relative_path in generated


def _parse_stem(raw: str) -> tuple[str | None, tuple[str, ...]]:
    cleaned = raw.strip()
    if cleaned.lower().endswith(".md"):
        cleaned = cleaned[:-3]
    if not cleaned:
        return None, ("memory note stem is required",)
    path = Path(cleaned.replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None, (
            "memory note stem must be a single flat segment without traversal",
        )
    if len(path.parts) != 1:
        return None, ("memory note stem must be a single flat segment",)
    if cleaned.lower() == _README_STEM:
        return None, ("memory note stem cannot be README",)
    if not _STEM_RE.fullmatch(cleaned):
        return None, ("memory note stem must match [A-Za-z0-9][A-Za-z0-9_-]*",)
    return cleaned, ()


def _parse_parent(raw: str) -> tuple[str | None, tuple[str, ...]]:
    cleaned = raw.strip().replace("\\", "/")
    if not cleaned or cleaned == AGENTS_PARENT:
        return AGENTS_PARENT, ()
    if any(part in {"", ".", ".."} for part in Path(cleaned).parts):
        return None, ("memory note parent must not contain traversal",)
    if Path(cleaned).is_absolute():
        return None, ("memory note parent must be a relative path",)
    relative = memory_note_relative_path(cleaned)
    if relative is None:
        if "/" in cleaned:
            return None, ("memory note parent must be AGENTS.md or a memory note path",)
        stem, stem_errors = _parse_stem(cleaned)
        if stem is None:
            return None, stem_errors or (
                "memory note parent must be AGENTS.md or a memory note path",
            )
        return memory_note_relative_path_for_stem(stem), ()
    if len(relative.parts) != 1 or relative.suffix != ".md":
        return None, ("memory note parent must be a flat memory note",)
    if relative.stem.lower() == _README_STEM:
        return None, ("memory note parent cannot be README.md",)
    return canonical_memory_reference(cleaned).as_posix(), ()


def _parent_legality_errors(
    *,
    note_relative_path: str,
    parent: str,
    notes_by_path: Mapping[str, MemoryNote],
) -> tuple[str, ...]:
    if parent == note_relative_path:
        return ("memory note parent cannot point at the note itself",)
    parent_note = notes_by_path.get(parent)
    if parent_note is None:
        return (f"memory note parent does not exist: {parent}",)
    if parent_note.type == "core":
        return (f"memory note parent is a core note: {parent}",)
    if parent_note.type != "reference":
        return (f"memory note parent is not a reference note: {parent}",)
    if _parent_chain_contains(
        start=parent,
        target=note_relative_path,
        notes_by_path=notes_by_path,
    ):
        return (f"memory note parent would create a cycle through {parent}",)
    return ()


def _parent_chain_contains(
    *,
    start: str,
    target: str,
    notes_by_path: Mapping[str, MemoryNote],
) -> bool:
    seen: set[str] = set()
    current = start
    while current != AGENTS_PARENT:
        if current == target:
            return True
        if current in seen:
            return True
        seen.add(current)
        parent_note = notes_by_path.get(current)
        if parent_note is None:
            return False
        current = parent_note.parent
    return False


def _normalize_description(description: str | None) -> str | None:
    if description is None:
        return None
    probe = apply_memory_frontmatter(
        "",
        note_type="reference",
        parent=AGENTS_PARENT,
        description=description,
    )
    return parse_memory_note_text(probe, "sase/memory/_draft.md").description


def _canonical_flat_note_path(raw: str) -> str | None:
    cleaned = raw.strip().replace("\\", "/")
    if not cleaned:
        return None
    path = Path(cleaned)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    relative = memory_note_relative_path(path)
    if relative is None:
        if len(path.parts) == 1 and path.suffix == ".md":
            relative = path
        else:
            return None
    if len(relative.parts) != 1 or relative.suffix != ".md":
        return None
    if relative.stem.lower() == _README_STEM:
        return None
    return (CANONICAL_MEMORY_RELATIVE_ROOT / relative).as_posix()


__all__ = [
    "children_of_memory_note",
    "memory_note_relative_path_for_stem",
    "raise_if_generated_memory_note",
    "raise_if_generated_memory_stem",
    "require_flat_memory_note_path",
    "validate_memory_note_draft",
]
