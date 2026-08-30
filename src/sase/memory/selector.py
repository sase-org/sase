"""Selector classification and batch resolution for ``memory read``/``show``.

``sase memory read``/``show`` accept three selector shapes in one variadic
batch: a flat note name (``foo.md``), a bare memory-web name (``glossary``,
every strand), and a ``web:keyword`` strand reference. The whole batch is
resolved before any output is produced or audit event written, so one
unknown selector fails the entire request with no partial output.

Authored ``[[target]]``/``![[target]]`` links (see :mod:`sase.memory.links`
and :mod:`sase.memory.link_resolve`) are resolved as part of this same batch:
a same-web inline link feeds the existing closure walk as an extra edge; a
cross-web or flat-note inline link adds an extra "related" root to its own
owning unit; every other resolved or unresolved link is collected onto its
source unit's ``resolved_links`` for the render layer's "Linked References".
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from sase.core.glossary_facade import GlossarySpanKind
from sase.main.init_memory.config import project_memory_name
from sase.memory.cli_common import MemoryCliProjectError, resolve_memory_cli_project
from sase.memory.link_resolve import (
    MemoryLinkTarget,
    MemoryNoteLinkTarget,
    MemoryStrandLinkTarget,
    MemoryWebDescriptorLinkTarget,
    UnresolvedMemoryLinkTarget,
    resolve_memory_link_target,
)
from sase.memory.links import MemoryLink, scan_memory_links
from sase.memory.notes import MemoryNote, discover_memory_notes
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    LEGACY_MEMORY_RELATIVE_ROOT,
)
from sase.memory.read_log import (
    MemoryReadError,
    MemoryReadPathError,
    read_memory_content,
    validate_memory_read_path,
)
from sase.memory.render import ResolvedMemoryNote
from sase.memory.web import (
    MemoryStrand,
    MemoryWeb,
    MemoryWebLookupError,
    ScopedMemoryWeb,
    StrandLinkSpan,
    WebScope,
    WebStrandOrigin,
    discover_scoped_memory_webs,
    resolve_memory_strand,
    resolve_strand_closure,
)
from sase.memory.web.resolution import GlossaryClosureNode

MemorySelectorKind = Literal["note", "web", "strand"]

# A cross-unit "extra root" leaf has no BFS depth of its own; it is a single
# related node hung off the linking strand, not a further expansion point.
_EXTRA_ROOT_DEPTH = 0


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
class MemoryWebReadNode:
    """One strand printed as part of a resolved web section."""

    strand: MemoryStrand
    scope: WebScope
    origin: Literal["requested", "related"]
    depth: int
    referrer: tuple[str, str, GlossarySpanKind] | None
    also_referenced_by: tuple[str, ...]


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


def resolve_memory_selector_batch(
    selectors: list[str],
    *,
    depth: int | None = None,
    project_ref: str | None = None,
    project_root: Path | None = None,
    home_root: Path | None = None,
) -> ResolvedMemorySelectorBatch:
    """Resolve every selector in *selectors* before any output is produced.

    *project_root* is a direct CWD override for tests and other in-process
    callers; CLI code should leave it unset and pass *project_ref* (the
    ``-p/--project`` value) instead.
    """
    if not selectors:
        raise _MemorySelectorError("at least one memory selector is required")

    resolved_home_root = home_root if home_root is not None else Path.home()
    try:
        cli_project = resolve_memory_cli_project(project_ref)
    except MemoryCliProjectError as exc:
        raise _MemorySelectorError(str(exc)) from exc
    if cli_project is not None:
        resolved_project_root = cli_project.project_root
        project_name = cli_project.project_name
    else:
        resolved_project_root = project_root if project_root is not None else Path.cwd()
        project_name = project_memory_name(resolved_project_root)
    project_root = resolved_project_root

    classified = [_classify_selector(raw) for raw in selectors]
    has_note = any(isinstance(item, _NoteSelector) for item in classified)
    has_web = any(isinstance(item, _WebSelector) for item in classified)
    has_strand = any(isinstance(item, _StrandSelector) for item in classified)

    link_notes, scoped_webs = _discover_link_universe(project_root, resolved_home_root)

    notes = tuple(
        _resolve_note_selector(
            item,
            project_root=project_root,
            home_root=resolved_home_root,
            project_name=project_name,
            notes=link_notes,
            scoped_webs=scoped_webs,
        )
        for item in classified
        if isinstance(item, _NoteSelector)
    )

    web_sections, extra_notes = _resolve_web_sections(
        classified,
        project_root=project_root,
        home_root=resolved_home_root,
        project_name=project_name,
        depth=depth,
        notes=link_notes,
        scoped_webs=scoped_webs,
    )
    known_note_paths = {note.content.path.canonical_path for note in notes}
    notes = notes + tuple(
        note
        for note in extra_notes
        if note.content.path.canonical_path not in known_note_paths
    )

    return ResolvedMemorySelectorBatch(
        project_name=project_name,
        notes=notes,
        web_sections=web_sections,
        selectors=tuple(selectors),
        depth=depth,
        has_note_selector=has_note,
        has_web_selector=has_web,
        has_strand_selector=has_strand,
    )


def _classify_selector(raw: str) -> _NoteSelector | _WebSelector | _StrandSelector:
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


def _discover_link_universe(
    project_root: Path, home_root: Path
) -> tuple[tuple[MemoryNote, ...], tuple[ScopedMemoryWeb, ...]]:
    """Return the project-over-home flat notes and scoped webs link targets resolve against."""
    project_notes = discover_memory_notes(project_root)
    resolved_project = project_root.resolve(strict=False)
    resolved_home = home_root.resolve(strict=False)
    home_notes = (
        () if resolved_home == resolved_project else discover_memory_notes(home_root)
    )
    by_path: dict[str, MemoryNote] = {}
    for note in (*project_notes, *home_notes):
        by_path.setdefault(note.relative_path, note)
    scoped_webs = discover_scoped_memory_webs(project_root, home_root)
    return tuple(by_path.values()), scoped_webs


def _resolve_note_selector(
    item: _NoteSelector,
    *,
    project_root: Path,
    home_root: Path,
    project_name: str,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
) -> ResolvedMemoryNote:
    try:
        validated_path = validate_memory_read_path(
            item.path,
            project_root=project_root,
            home_root=home_root,
        )
    except MemoryReadPathError as exc:
        raise _MemorySelectorError(_note_selector_error(item, exc)) from exc

    content = read_memory_content(validated_path)
    children = discover_memory_notes(content.path.content_root)
    resolved_home_root = home_root.expanduser().resolve(strict=False)
    origin: Literal["home", "project"] = (
        "home" if content.path.content_root == resolved_home_root else "project"
    )
    resolved_links = _resolve_note_links(
        content.body,
        source_note=content.path.note,
        notes=notes,
        scoped_webs=scoped_webs,
    )
    return ResolvedMemoryNote(
        content=content,
        children=children,
        origin=origin,
        project_name=project_name,
        resolved_links=resolved_links,
    )


def _note_selector_error(item: _NoteSelector, exc: MemoryReadPathError) -> str:
    """Suggest a ``web:keyword`` selector for a nested-looking ``.md`` typo."""
    message = str(exc)
    if "flat" not in message:
        return message

    parts = Path(item.path).parts
    for prefix in (
        CANONICAL_MEMORY_RELATIVE_ROOT.parts,
        LEGACY_MEMORY_RELATIVE_ROOT.parts,
    ):
        if parts[: len(prefix)] == prefix:
            parts = parts[len(prefix) :]
            break
    if len(parts) == 2 and parts[1].endswith(".md"):
        web_slug, keyword = parts[0], parts[1][: -len(".md")]
        return f"{message}; did you mean {web_slug}:{keyword}?"
    return message


def _resolve_note_links(
    body: str,
    *,
    source_note: MemoryNote,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
) -> tuple[MemoryLinkTarget, ...]:
    """Scan and resolve *source_note*'s authored links.

    Flat notes have no established closure/BFS walk to feed, so every
    resolved (or unresolved) link renders as a reference entry regardless of
    the ``!`` prefix or the note's own ``link_rendering``.
    """
    if source_note.link_reference == "none":
        return ()
    resolved: list[MemoryLinkTarget] = []
    seen: set[str] = set()
    for link in scan_memory_links(body):
        target = resolve_memory_link_target(
            link.target,
            notes=notes,
            scoped_webs=scoped_webs,
            source_note=source_note,
        )
        if target is None:
            continue
        key = _link_target_key(target)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(target)
    return tuple(resolved)


@dataclass(frozen=True, slots=True)
class _ResolvedStrandLink:
    """One authored link from a strand, fully resolved against the read universe."""

    strand: MemoryStrand
    link: MemoryLink
    inline: bool
    target: MemoryLinkTarget


def _always_reference_target(target: MemoryLinkTarget) -> bool:
    """Return whether *target* must always render as a reference, never inline.

    Always-loaded context -- a web descriptor or a ``type: core`` flat note --
    can't be read via ``sase memory read``, so it can never be inlined.
    """
    if isinstance(target, MemoryWebDescriptorLinkTarget):
        return True
    if isinstance(target, MemoryNoteLinkTarget):
        return target.note.type == "core"
    return False


def _resolve_strand_links(
    universe: tuple[MemoryStrand, ...],
    *,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    depth: int | None,
) -> tuple[_ResolvedStrandLink, ...]:
    """Scan and resolve every authored link in *universe*'s strand bodies.

    ``-d 0`` prints only the requested strands, so every link is classified as
    a reference at depth zero rather than expanded.
    """
    edges: list[_ResolvedStrandLink] = []
    for strand in universe:
        if strand.link_reference == "none":
            continue
        for link in scan_memory_links(strand.body):
            target = resolve_memory_link_target(
                link.target,
                notes=notes,
                scoped_webs=scoped_webs,
                source_strand=strand,
            )
            if target is None:
                continue
            inline = depth != 0 and (link.inline or strand.link_rendering == "inline")
            if inline and _always_reference_target(target):
                inline = False
            edges.append(
                _ResolvedStrandLink(
                    strand=strand, link=link, inline=inline, target=target
                )
            )
    return tuple(edges)


def _link_target_key(target: MemoryLinkTarget) -> str:
    if isinstance(target, UnresolvedMemoryLinkTarget):
        return f"unresolved:{target.raw}"
    return f"{target.kind}:{target.address}"


def _resolve_web_sections(
    classified: list[_NoteSelector | _WebSelector | _StrandSelector],
    *,
    project_root: Path,
    home_root: Path,
    project_name: str,
    depth: int | None,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
) -> tuple[tuple[MemoryWebReadSection, ...], tuple[ResolvedMemoryNote, ...]]:
    web_items = [
        item for item in classified if isinstance(item, (_WebSelector, _StrandSelector))
    ]
    if not web_items:
        return (), ()

    by_slug = {scoped.slug: scoped for scoped in scoped_webs}

    order: list[str] = []
    requested_slugs: dict[str, set[str]] = {}
    for item in web_items:
        scoped = by_slug.get(item.web_slug)
        if scoped is None:
            raise _MemorySelectorError(f"unknown memory web: {item.web_slug}")
        if item.web_slug not in requested_slugs:
            requested_slugs[item.web_slug] = set()
            order.append(item.web_slug)
        if isinstance(item, _WebSelector):
            requested_slugs[item.web_slug].update(
                strand.slug for strand in scoped.strands
            )
            continue
        merged_web = replace(scoped.web, strands=scoped.strands)
        try:
            strand = resolve_memory_strand(merged_web, item.keyword)
        except MemoryWebLookupError as exc:
            raise _MemorySelectorError(str(exc)) from exc
        requested_slugs[item.web_slug].add(strand.slug)

    sections: list[MemoryWebReadSection] = []
    cross_web_pending: list[
        tuple[MemoryStrand, MemoryStrandLinkTarget, MemoryLink]
    ] = []
    cross_note_pending: list[MemoryNoteLinkTarget] = []

    for slug in order:
        scoped = by_slug[slug]
        merged_web = replace(scoped.web, strands=scoped.strands)
        wanted = requested_slugs[slug]
        roots = tuple(strand for strand in scoped.strands if strand.slug in wanted)

        link_edges = _resolve_strand_links(
            scoped.strands, notes=notes, scoped_webs=scoped_webs, depth=depth
        )
        same_web_spans = tuple(
            StrandLinkSpan(
                source_slug=edge.strand.slug,
                target_slug=edge.target.strand.slug,
                raw=edge.link.raw,
                span=edge.link.span,
            )
            for edge in link_edges
            if edge.inline
            and isinstance(edge.target, MemoryStrandLinkTarget)
            and edge.target.web.slug == slug
        )

        closure, strand_by_index = resolve_strand_closure(
            merged_web, scoped.strands, roots, depth=depth, link_spans=same_web_spans
        )
        nodes = tuple(
            _closure_node(node, strand_by_index, scoped.origins)
            for node in closure.nodes
        )
        rendered_slugs = {node.strand.slug for node in nodes}

        resolved_links: list[MemoryLinkTarget] = []
        seen_link_keys: set[str] = set()
        for edge in link_edges:
            if edge.strand.slug not in rendered_slugs:
                continue
            if edge.inline and isinstance(edge.target, MemoryStrandLinkTarget):
                if edge.target.web.slug == slug:
                    continue  # already inline-expanded via the closure spans
                cross_web_pending.append((edge.strand, edge.target, edge.link))
                continue
            if edge.inline and isinstance(edge.target, MemoryNoteLinkTarget):
                cross_note_pending.append(edge.target)
                continue
            key = _link_target_key(edge.target)
            if key in seen_link_keys:
                continue
            seen_link_keys.add(key)
            resolved_links.append(edge.target)

        sections.append(
            MemoryWebReadSection(
                web=merged_web,
                nodes=nodes,
                depth_limit=closure.depth_limit,
                truncated=closure.truncated,
                resolved_links=tuple(resolved_links),
            )
        )

    for source_strand, strand_target, link in cross_web_pending:
        _apply_cross_web_root(sections, by_slug, source_strand, strand_target, link)

    extra_notes: list[ResolvedMemoryNote] = []
    seen_note_paths: set[str] = set()
    for note_target in cross_note_pending:
        note = _resolve_extra_note(
            note_target,
            project_root=project_root,
            home_root=home_root,
            project_name=project_name,
            notes=notes,
            scoped_webs=scoped_webs,
        )
        if note is None:
            continue
        canonical_path = note.content.path.canonical_path
        if canonical_path in seen_note_paths:
            continue
        seen_note_paths.add(canonical_path)
        extra_notes.append(note)

    return tuple(sections), tuple(extra_notes)


def _apply_cross_web_root(
    sections: list[MemoryWebReadSection],
    by_slug: dict[str, ScopedMemoryWeb],
    source_strand: MemoryStrand,
    target: MemoryStrandLinkTarget,
    link: MemoryLink,
) -> None:
    """Add *target* as an extra related root, creating its section if needed."""
    node = MemoryWebReadNode(
        strand=target.strand,
        scope=target.scope,
        origin="related",
        depth=_EXTRA_ROOT_DEPTH,
        referrer=(source_strand.keyword, link.raw, "link"),
        also_referenced_by=(),
    )
    for index, section in enumerate(sections):
        if section.web.slug != target.web.slug:
            continue
        if any(
            existing.strand.slug == target.strand.slug for existing in section.nodes
        ):
            return
        sections[index] = replace(section, nodes=section.nodes + (node,))
        return

    scoped = by_slug.get(target.web.slug)
    if scoped is None:
        return
    merged_web = replace(scoped.web, strands=scoped.strands)
    sections.append(
        MemoryWebReadSection(
            web=merged_web,
            nodes=(node,),
            depth_limit=None,
            truncated=False,
        )
    )


def _resolve_extra_note(
    target: MemoryNoteLinkTarget,
    *,
    project_root: Path,
    home_root: Path,
    project_name: str,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
) -> ResolvedMemoryNote | None:
    """Resolve a cross-unit inline note target as its own read unit.

    Falls back to ``None`` (the caller then leaves the raw link as a
    reference) rather than raising: an authored inline link that fails
    validation should degrade gracefully, not fail the whole batch.
    """
    selector = _NoteSelector(raw=target.address, path=target.address)
    try:
        return _resolve_note_selector(
            selector,
            project_root=project_root,
            home_root=home_root,
            project_name=project_name,
            notes=notes,
            scoped_webs=scoped_webs,
        )
    except MemoryReadError:
        return None


def _closure_node(
    node: GlossaryClosureNode,
    strand_by_index: dict[int, MemoryStrand],
    origins: dict[str, WebStrandOrigin],
) -> MemoryWebReadNode:
    strand = strand_by_index[node.entry.index]
    return MemoryWebReadNode(
        strand=strand,
        scope=origins[strand.slug].scope,
        origin=node.origin,
        depth=node.depth,
        referrer=(
            None
            if node.referrer is None
            else (node.referrer.term, node.referrer.matched_text, node.referrer.kind)
        ),
        also_referenced_by=node.also_referenced_by,
    )


__all__ = [
    "MemorySelectorKind",
    "MemoryWebReadNode",
    "MemoryWebReadSection",
    "ResolvedMemorySelectorBatch",
    "resolve_memory_selector_batch",
]
