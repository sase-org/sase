"""Delete confirmation copy and neighbor reselect for the Memory panel."""

from __future__ import annotations

from collections.abc import Sequence

from sase.memory.notes import MemoryNote
from sase.memory.web.models import MemoryStrand, MemoryWeb


def build_memory_delete_subject(
    note: MemoryNote,
    *,
    child_count: int,
) -> str:
    """Build the confirm-dialog subject for deleting *note*."""
    first_line = next(
        (
            line.strip()
            for line in (note.description or "").splitlines()
            if line.strip()
        ),
        "",
    )
    tier = "1 (core)" if note.type == "core" else "2 (reference)"
    child_word = "child" if child_count == 1 else "children"
    lines = [
        f"Note: {note.relative_path}",
        f"Tier: {tier}",
        f"Description: {first_line or '(empty)'}",
        f"Children: {child_count} {child_word}",
    ]
    if note.type == "core":
        lines.append(
            "WARNING: deleting a core note removes always-loaded agent context."
        )
    return "\n".join(lines)


def build_memory_strand_delete_subject(
    web: MemoryWeb,
    strand: MemoryStrand,
    *,
    referenced_by: Sequence[str] = (),
) -> str:
    """Build the confirm-dialog subject for deleting *strand* from *web*."""
    first_line = next(
        (line.strip() for line in strand.body.splitlines() if line.strip()),
        "",
    )
    lines = [
        f"Strand: {strand.relative_path}",
        f"Keyword: {strand.keyword}",
        f"Aliases: {', '.join(strand.aliases) if strand.aliases else '(none)'}",
        f"Body: {first_line or '(empty)'}",
    ]
    if referenced_by:
        lines.append(f"Referenced by: {', '.join(referenced_by)}")
    return "\n".join(lines)


def build_child_blocked_delete_message(children: Sequence[MemoryNote]) -> str:
    """Explain why a note with children cannot be deleted."""
    named = ", ".join(child.relative_path for child in children)
    return (
        "This note has children and cannot be deleted until they are "
        f"reparented: {named}"
    )


def neighbor_note_after_delete(paths: Sequence[str], deleted_path: str) -> str | None:
    """Return the note that should stay selected after *deleted_path* is removed."""
    visible = list(paths)
    try:
        index = visible.index(deleted_path)
    except ValueError:
        return visible[-1] if visible else None
    remaining = [path for path in visible if path != deleted_path]
    if not remaining:
        return None
    if index >= len(remaining):
        return remaining[-1]
    return remaining[index]


def children_of(
    notes: Sequence[MemoryNote], relative_path: str
) -> tuple[MemoryNote, ...]:
    """Return *relative_path*'s children, sorted by path."""
    children = [note for note in notes if note.parent == relative_path]
    return tuple(sorted(children, key=lambda note: note.relative_path))


__all__ = [
    "build_child_blocked_delete_message",
    "build_memory_delete_subject",
    "build_memory_strand_delete_subject",
    "children_of",
    "neighbor_note_after_delete",
]
