"""Shared substring filter over snippet triggers, aliases, sources, and bodies.

Used by ``sase snippet list`` and the ACE snippets panel's ``/`` filter so
both apply the same casefold matching semantics.
"""

from __future__ import annotations

from sase.snippet.models import SnippetEntry


def filter_snippet_entries(
    entries: tuple[SnippetEntry, ...],
    *,
    pattern: str | None,
    include_definitions: bool = False,
    include_bodies: bool | None = None,
) -> tuple[SnippetEntry, ...]:
    """Return the entries in *entries* whose trigger/aliases/sources match *pattern*.

    A falsy ``pattern`` returns *entries* unchanged. Matching is a casefolded
    substring test against each entry's trigger, generated aliases, and source
    labels, plus its raw and composed templates when template matching is on.
    ``include_bodies`` is the panel alias for ``include_definitions``.
    """
    if not pattern:
        return entries
    include_templates = (
        include_definitions if include_bodies is None else include_bodies
    )
    needle = pattern.casefold()
    matched: list[SnippetEntry] = []
    for entry in entries:
        haystacks = [
            entry.trigger,
            *entry.aliases,
            entry.origin.kind,
            entry.origin.display_path or "",
            entry.origin.path or "",
            entry.origin.xprompt_name or "",
        ]
        if include_templates:
            haystacks.extend((entry.raw_template, entry.composed_template))
        if any(needle in haystack.casefold() for haystack in haystacks if haystack):
            matched.append(entry)
    return tuple(matched)


__all__ = ["filter_snippet_entries"]
