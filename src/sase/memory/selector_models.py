"""Shared types and selector classification for memory selector resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.core.glossary_facade import GlossarySpanKind
from sase.memory.link_resolve import (
    MemoryLinkTarget,
    MemoryNoteLinkTarget,
    MemoryStrandLinkTarget,
    UnresolvedMemoryLinkTarget,
)
from sase.memory.links import MemoryLink
from sase.memory.notes import MemoryNote
from sase.memory.read_log import MemoryReadError
from sase.memory.render import ResolvedMemoryNote, ResolvedMemoryNoteLink
from sase.memory.selector_postprocess import MemorySelectorBatchUnit
from sase.memory.web import MemoryStrand, MemoryWeb, WebScope

MemorySelectorKind = Literal["note", "web", "strand"]


class _MemorySelectorError(MemoryReadError):
    """Raised when a memory selector in a read/show batch cannot be resolved."""


@dataclass(frozen=True, slots=True)
class _NoteSelector:
    raw: str
    path: str


@dataclass(frozen=True, slots=True)
class _WebSelector:
    raw: str
    web_slug: str


@dataclass(frozen=True, slots=True)
class _StrandSelector:
    raw: str
    web_slug: str
    keyword: str


@dataclass(frozen=True, slots=True)
class _MemoryWebReadLink:
    """One authored link from a rendered strand, classified for output."""

    target: MemoryLinkTarget
    kind: Literal["inline", "reference"]


@dataclass(frozen=True, slots=True)
class _ResolvedNoteLinks:
    """Authored flat-note links split into render and reference targets."""

    links: tuple[ResolvedMemoryNoteLink, ...]
    inline_notes: tuple[ResolvedMemoryNote, ...]
    references: tuple[MemoryLinkTarget, ...]


@dataclass(frozen=True, slots=True)
class _PendingNoteStrandRoot:
    """One flat-note inline link to a web strand awaiting section rendering."""

    source_note: MemoryNote
    target: MemoryStrandLinkTarget
    link: MemoryLink


@dataclass(slots=True)
class _NoteInlineContext:
    """Mutable cross-batch state for flat-note inline resolution."""

    pending_strand_roots: list[_PendingNoteStrandRoot]


@dataclass(frozen=True, slots=True)
class MemoryWebReadNode:
    """One strand printed as part of a resolved web section."""

    strand: MemoryStrand
    scope: WebScope
    origin: Literal["requested", "related"]
    depth: int
    referrer: tuple[str, str, GlossarySpanKind] | None
    also_referenced_by: tuple[str, ...]
    links: tuple[_MemoryWebReadLink, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryWebReadSection:
    """Every strand read from one web in a batch, in closure order."""

    web: MemoryWeb
    nodes: tuple[MemoryWebReadNode, ...]
    depth_limit: int | None
    truncated: bool
    resolved_links: tuple[MemoryLinkTarget, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedMemorySelectorBatch:
    """A fully resolved, not-yet-rendered ``memory read``/``show`` batch."""

    project_name: str
    notes: tuple[ResolvedMemoryNote, ...]
    web_sections: tuple[MemoryWebReadSection, ...]
    selectors: tuple[str, ...]
    depth: int | None
    has_note_selector: bool
    has_web_selector: bool
    has_strand_selector: bool
    render_units: tuple[MemorySelectorBatchUnit, ...] = ()

    @property
    def kind(self) -> MemorySelectorKind:
        if self.has_web_selector:
            return "web"
        if self.has_strand_selector:
            return "strand"
        return "note"

    @property
    def is_single_note(self) -> bool:
        return len(self.notes) == 1 and not self.web_sections


@dataclass(frozen=True, slots=True)
class _ResolvedStrandLink:
    """One authored link from a strand, resolved against the read universe."""

    strand: MemoryStrand
    link: MemoryLink
    inline: bool
    target: MemoryLinkTarget


def classify_selector(raw: str) -> _NoteSelector | _WebSelector | _StrandSelector:
    """Classify one user-supplied flat-note, web, or strand selector."""
    stripped = raw.strip()
    if not stripped:
        raise _MemorySelectorError("memory selector must not be empty")
    if ":" in stripped:
        web_part, _, keyword_part = stripped.partition(":")
        web_part = web_part.strip()
        keyword_part = keyword_part.strip()
        if not web_part or not keyword_part:
            raise _MemorySelectorError(f"invalid memory selector: {raw!r}")
        return _StrandSelector(raw=raw, web_slug=web_part, keyword=keyword_part)
    if stripped.endswith(".md"):
        return _NoteSelector(raw=raw, path=stripped)
    return _WebSelector(raw=raw, web_slug=stripped)


def link_target_key(target: MemoryLinkTarget) -> str:
    """Return a stable identity key for a resolved or unresolved link target."""
    if isinstance(target, UnresolvedMemoryLinkTarget):
        return f"unresolved:{target.raw}"
    return f"{target.kind}:{target.address}"


def always_reference_target(target: MemoryLinkTarget) -> bool:
    """Return whether *target* cannot be expanded into a read result."""
    from sase.memory.link_resolve import MemoryWebDescriptorLinkTarget

    if isinstance(target, MemoryWebDescriptorLinkTarget):
        return True
    if isinstance(target, MemoryNoteLinkTarget):
        return target.note.type == "core"
    return False
