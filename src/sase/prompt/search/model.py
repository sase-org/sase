"""Source-agnostic data model for the unified prompt search corpus.

A :class:`PromptHit` is one prompt drawn from either store (a committed SDD
snapshot or a local prompt-history entry), normalized to a single shape so the
engine and renderers never branch on provenance beyond the :attr:`PromptHit.source`
tag. The model is pure data: no IO, no rendering, no presentation truncation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class PromptSource(StrEnum):
    """Which store a :class:`PromptHit` came from.

    :class:`~enum.StrEnum` keeps the value JSON-friendly (``"sdd"`` / ``"local"``)
    and directly comparable to the ``-s/--source`` CLI argument.
    """

    SDD = "sdd"
    LOCAL = "local"


@dataclass(frozen=True)
class PromptHit:
    """One unified search candidate from the SDD or local prompt store.

    The fields deliberately cover both stores; presentation-only concerns
    (highlighting, truncation, colored badges) live in the renderers, not here.

    Attributes:
        source: Which store the hit came from.
        id: Stable locator. SDD: the repo-relative path stem (e.g.
            ``kitty_image_panel_fix``). Local: the ``ph_<sha256[:12]>`` content
            ID that ``sase prompt show/run/edit`` already accept.
        text: The prompt body. SDD: the markdown body with frontmatter and the
            system artifact-link bullet stripped. Local: the exact recorded
            prompt text.
        title: A cleaned one-line preview of the prompt, falling back to the
            locator when the body has no usable line.
        date: A comparable SASE ``YYmmdd_HHMMSS`` timestamp resolved via the
            documented per-source precedence (see :mod:`sase.prompt.search.dates`).
            This is the value ``--after``/``--before`` filter against.
        text_sha256: SDD: the recorded frontmatter ``sha256`` when present, else
            the digest computed over :attr:`text`. Local: the entry's content
            digest. Drives best-effort cross-store de-duplication.
        path: SDD: the repo-relative file path. Local: ``None`` (the store is a
            single JSON file).
        plan: SDD: the visible ``PLAN`` artifact-link label (the tale/epic it
            produced). Local: ``None``.
        tags: Sigil-stripped, de-duplicated tag tokens drawn from SDD
            ``prompt_tags`` frontmatter and the ``#xprompt`` chips embedded in
            the body.
        cancelled: Local: the entry's cancelled flag. SDD: ``None`` (snapshots
            have no cancelled state).
        also_in_local: ``True`` on an SDD hit when a local entry with the same
            ``text_sha256`` was collapsed into it during de-duplication.
    """

    source: PromptSource
    id: str
    text: str
    title: str
    date: str
    text_sha256: str
    path: str | None = None
    plan: str | None = None
    tags: tuple[str, ...] = ()
    cancelled: bool | None = None
    also_in_local: bool = False

    @property
    def text_chars(self) -> int:
        """Return the character length of the prompt text."""
        return len(self.text)


@dataclass(frozen=True)
class PromptSearchMatch:
    """A :class:`PromptHit` that matched, with the fields that matched recorded.

    ``matched_fields`` is what lets the renderers tell the user *why* a hit
    matched (and highlight the right place). Field names are the stable tokens
    ``title``, ``body``, ``id``, ``path``, ``plan``, and ``tags``.
    """

    hit: PromptHit
    matched_fields: tuple[str, ...]


@dataclass(frozen=True)
class PromptSearchResult:
    """The result envelope returned by the search engine.

    Attributes:
        query: The literal query that produced these matches.
        matches: The ranked, **post-limit** matches actually shown.
        total: Total matches before the limit was applied, so truncation is
            always reportable (``showing len(matches) of total``).
        counts: Per-source **pre-limit** match totals. Always carries an entry
            for every :class:`PromptSource` so output can show ``0`` explicitly.
    """

    query: str
    matches: tuple[PromptSearchMatch, ...]
    total: int
    counts: Mapping[PromptSource, int] = field(default_factory=dict)

    @property
    def count(self) -> int:
        """Return how many matches are shown (post-limit)."""
        return len(self.matches)

    def count_for(self, source: PromptSource) -> int:
        """Return the pre-limit match total for *source* (``0`` when absent)."""
        return self.counts.get(source, 0)
