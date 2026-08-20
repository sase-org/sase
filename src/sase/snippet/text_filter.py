"""Shared substring filter over snippet triggers, aliases, and bodies.

Used by ``sase snippet list`` so the CLI applies the same casefold matching
semantics the catalog's lookup surface documents.
"""

from __future__ import annotations

from sase.snippet.models import SnippetEntry


def filter_snippet_entries(
    entries: tuple[SnippetEntry, ...],
    *,
    pattern: str | None,
    include_definitions: bool,
) -> tuple[SnippetEntry, ...]:
    """Return the entries in *entries* whose trigger/aliases match *pattern*.

    A falsy ``pattern`` returns *entries* unchanged. Matching is a casefolded
    substring test against each entry's trigger and generated aliases, plus
    its raw and composed templates when *include_definitions* is set.
    """
    if not pattern:
        return entries
    needle = pattern.casefold()
    matched: list[SnippetEntry] = []
    for entry in entries:
        haystacks = [entry.trigger, *entry.aliases]
        if include_definitions:
            haystacks.extend((entry.raw_template, entry.composed_template))
        if any(needle in haystack.casefold() for haystack in haystacks):
            matched.append(entry)
    return tuple(matched)


__all__ = ["filter_snippet_entries"]
