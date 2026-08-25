"""Shared substring filter over memory-note stems, descriptions, and bodies.

Used by the ACE Memory panel's ``/`` filter and CLI list surfaces so every
matcher applies the same casefold semantics.
"""

from __future__ import annotations

from collections.abc import Iterable

from sase.memory.notes import MemoryNote


def filter_memory_notes(
    notes: Iterable[MemoryNote],
    *,
    pattern: str | None,
    include_bodies: bool,
) -> tuple[MemoryNote, ...]:
    """Return the notes in *notes* whose stem or description match *pattern*.

    A falsy ``pattern`` returns *notes* unchanged. Matching is a casefolded
    substring test against each note's stem and description, plus its body
    when *include_bodies* is set.
    """
    materialized = tuple(notes)
    if not pattern:
        return materialized
    needle = pattern.casefold()
    matched: list[MemoryNote] = []
    for note in materialized:
        haystacks = [note.path.stem]
        if note.description:
            haystacks.append(note.description)
        if include_bodies:
            haystacks.append(note.body)
        if any(needle in haystack.casefold() for haystack in haystacks):
            matched.append(note)
    return tuple(matched)


__all__ = ["filter_memory_notes"]
