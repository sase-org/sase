"""Shared substring filter over glossary terms, aliases, and definitions.

Used by ``sase glossary list`` and the ACE glossary panel's ``/`` filter so
both apply identical casefold matching semantics.
"""

from __future__ import annotations

from sase.core.glossary_facade import GlossaryEntry


def filter_glossary_entries(
    entries: tuple[GlossaryEntry, ...],
    *,
    pattern: str | None,
    include_definitions: bool,
) -> tuple[GlossaryEntry, ...]:
    """Return the entries in *entries* whose term/aliases match *pattern*.

    A falsy ``pattern`` returns *entries* unchanged. Matching is a casefolded
    substring test against each entry's term and display aliases, plus its
    definition when *include_definitions* is set.
    """
    if not pattern:
        return entries
    needle = pattern.casefold()
    matched: list[GlossaryEntry] = []
    for entry in entries:
        haystacks = [entry.term, *entry.display_aliases]
        if include_definitions:
            haystacks.append(entry.definition)
        if any(needle in haystack.casefold() for haystack in haystacks):
            matched.append(entry)
    return tuple(matched)


__all__ = ["filter_glossary_entries"]
