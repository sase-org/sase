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
from sase.memory.render import ResolvedMemoryNote, ResolvedMemoryNoteLink
from sase.memory.selector_postprocess import (
    MemorySelectorBatchUnit,
    select_memory_selector_render_units,
    suppress_rendered_targets,
)
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

    note_items = [item for item in classified if isinstance(item, _NoteSelector)]
    requested_note_keys = _requested_note_keys(
        note_items, project_root=project_root, home_root=resolved_home_root
    )
    note_inline_context = _NoteInlineContext(pending_strand_roots=[])
    note_roots_seen: set[str] = set()
    rendered_note_keys: set[str] = set()
    resolved_notes: list[ResolvedMemoryNote] = []
    for item in note_items:
        item_keys = _note_selector_keys(
            item, project_root=project_root, home_root=resolved_home_root
        )
        if item_keys & note_roots_seen:
            continue
        note = _resolve_note_selector(
            item,
            project_root=project_root,
            home_root=resolved_home_root,
            project_name=project_name,
            notes=link_notes,
            scoped_webs=scoped_webs,
            depth=depth,
            seen_note_paths=frozenset(requested_note_keys | rendered_note_keys),
            note_inline_context=note_inline_context,
        )
        resolved_notes.append(note)
        note_roots_seen.update(item_keys)
        rendered_note_keys.update(_note_tree_keys(note))
    notes = tuple(resolved_notes)

    web_sections, extra_notes = _resolve_web_sections(
        classified,
        project_root=project_root,
        home_root=resolved_home_root,
        project_name=project_name,
        depth=depth,
        notes=link_notes,
        scoped_webs=scoped_webs,
        note_inline_context=note_inline_context,
        rendered_note_keys=frozenset(rendered_note_keys),
    )
    known_note_paths = {
        key
        for note in notes
        for key in _validated_note_keys(
            note.content.path.canonical_path,
            note.content.path.note,
        )
    }
    notes = notes + tuple(
        note
        for note in extra_notes
        if not (
            _validated_note_keys(
                note.content.path.canonical_path, note.content.path.note
            )
            & known_note_paths
        )
    )

    web_sections = _apply_note_strand_roots(
        web_sections,
        note_inline_context.pending_strand_roots,
        scoped_webs=scoped_webs,
    )
    notes, web_sections = suppress_rendered_targets(
        notes,
        web_sections,
        link_target_key=_link_target_key,
    )
    render_units = select_memory_selector_render_units(
        _render_unit_candidates(
            classified,
            project_root=project_root,
            home_root=resolved_home_root,
        ),
        notes,
        web_sections,
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
        render_units=render_units,
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


def _requested_note_keys(
    items: list[_NoteSelector],
    *,
    project_root: Path,
    home_root: Path,
) -> frozenset[str]:
    """Return identity keys for top-level note selectors in the batch."""
    keys: set[str] = set()
    for item in items:
        keys.update(
            _note_selector_keys(
                item,
                project_root=project_root,
                home_root=home_root,
            )
        )
    return frozenset(keys)


def _note_selector_keys(
    item: _NoteSelector,
    *,
    project_root: Path,
    home_root: Path,
) -> frozenset[str]:
    """Return identity keys for one top-level note selector."""
    try:
        validated_path = validate_memory_read_path(
            item.path,
            project_root=project_root,
            home_root=home_root,
        )
    except MemoryReadPathError as exc:
        raise _MemorySelectorError(_note_selector_error(item, exc)) from exc
    return _validated_note_keys(validated_path.canonical_path, validated_path.note)


def _note_selector_canonical_path(
    item: _NoteSelector,
    *,
    project_root: Path,
    home_root: Path,
) -> str:
    """Return the canonical path for one top-level note selector."""
    try:
        validated_path = validate_memory_read_path(
            item.path,
            project_root=project_root,
            home_root=home_root,
        )
    except MemoryReadPathError as exc:
        raise _MemorySelectorError(_note_selector_error(item, exc)) from exc
    return validated_path.canonical_path


def _validated_note_keys(canonical_path: str, note: MemoryNote) -> frozenset[str]:
    """Return equivalent path keys that identify one flat memory note."""
    return frozenset({canonical_path, note.relative_path})


def _note_target_keys(target: MemoryNoteLinkTarget) -> frozenset[str]:
    """Return equivalent path keys that identify a note link target."""
    return frozenset({target.address, target.note.relative_path})


def _note_tree_keys(view: ResolvedMemoryNote) -> frozenset[str]:
    """Return identity keys for every note rendered by *view*."""
    keys: set[str] = set(
        _validated_note_keys(view.content.path.canonical_path, view.content.path.note)
    )
    for inline_note in view.inline_notes:
        keys.update(_note_tree_keys(inline_note))
    return frozenset(keys)


def _resolve_note_selector(
    item: _NoteSelector,
    *,
    project_root: Path,
    home_root: Path,
    project_name: str,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    depth: int | None,
    seen_note_paths: frozenset[str] = frozenset(),
    note_inline_context: _NoteInlineContext | None = None,
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
    current_seen = set(seen_note_paths)
    current_seen.update(
        _validated_note_keys(content.path.canonical_path, content.path.note)
    )
    resolved = _resolve_note_links(
        content.body,
        source_note=content.path.note,
        notes=notes,
        scoped_webs=scoped_webs,
        depth=depth,
        project_root=project_root,
        home_root=home_root,
        project_name=project_name,
        seen_note_paths=frozenset(current_seen),
        note_inline_context=note_inline_context,
    )
    return ResolvedMemoryNote(
        content=content,
        children=children,
        origin=origin,
        project_name=project_name,
        resolved_links=resolved.references,
        links=resolved.links,
        inline_notes=resolved.inline_notes,
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
    depth: int | None,
    project_root: Path,
    home_root: Path,
    project_name: str,
    seen_note_paths: frozenset[str],
    note_inline_context: _NoteInlineContext | None,
) -> _ResolvedNoteLinks:
    """Scan and resolve *source_note*'s authored links.

    ``-d 0`` prints only the requested note, so every link is classified as
    a reference at depth zero rather than expanded.
    """
    if source_note.link_reference == "none":
        return _ResolvedNoteLinks(links=(), inline_notes=(), references=())
    links: list[ResolvedMemoryNoteLink] = []
    inline_notes: list[ResolvedMemoryNote] = []
    references: list[MemoryLinkTarget] = []
    seen_references: set[str] = set()
    seen_rendered_notes = set(seen_note_paths)

    def add_reference(target: MemoryLinkTarget) -> None:
        key = _link_target_key(target)
        if key in seen_references:
            return
        seen_references.add(key)
        references.append(target)

    def remove_reference(target: MemoryLinkTarget) -> None:
        key = _link_target_key(target)
        if key not in seen_references:
            return
        seen_references.remove(key)
        references[:] = [
            reference for reference in references if _link_target_key(reference) != key
        ]

    for link in scan_memory_links(body):
        target = resolve_memory_link_target(
            link.target,
            notes=notes,
            scoped_webs=scoped_webs,
            source_note=source_note,
        )
        if target is None:
            continue
        inline = depth != 0 and (link.inline or source_note.link_rendering == "inline")
        if inline and _always_reference_target(target):
            inline = False
        kind: Literal["inline", "reference"] = "inline" if inline else "reference"
        links.append(ResolvedMemoryNoteLink(target=target, kind=kind))

        if isinstance(target, MemoryNoteLinkTarget):
            target_keys = _note_target_keys(target)
            if target_keys & seen_rendered_notes:
                continue
            if inline:
                inline_note = _resolve_extra_note(
                    target,
                    project_root=project_root,
                    home_root=home_root,
                    project_name=project_name,
                    notes=notes,
                    scoped_webs=scoped_webs,
                    depth=None if depth is None else depth - 1,
                    seen_note_paths=frozenset(seen_rendered_notes | set(target_keys)),
                    note_inline_context=note_inline_context,
                )
                if inline_note is not None:
                    inline_notes.append(inline_note)
                    seen_rendered_notes.update(_note_tree_keys(inline_note))
                    remove_reference(target)
                    for reference in inline_note.resolved_links:
                        add_reference(reference)
                    continue
            add_reference(target)
            continue

        if inline and isinstance(target, MemoryStrandLinkTarget):
            if note_inline_context is not None:
                note_inline_context.pending_strand_roots.append(
                    _PendingNoteStrandRoot(
                        source_note=source_note,
                        target=target,
                        link=link,
                    )
                )
            continue

        add_reference(target)
    return _ResolvedNoteLinks(
        links=tuple(links),
        inline_notes=tuple(inline_notes),
        references=tuple(references),
    )


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
    note_inline_context: _NoteInlineContext,
    rendered_note_keys: frozenset[str] = frozenset(),
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
        rendered_slugs = {
            strand_by_index[node.entry.index].slug for node in closure.nodes
        }

        node_links: dict[str, list[_MemoryWebReadLink]] = {}
        resolved_links: list[MemoryLinkTarget] = []
        seen_link_keys: set[str] = set()
        for edge in link_edges:
            if edge.strand.slug not in rendered_slugs:
                continue
            kind: Literal["inline", "reference"] = (
                "inline" if edge.inline else "reference"
            )
            node_links.setdefault(edge.strand.slug, []).append(
                _MemoryWebReadLink(target=edge.target, kind=kind)
            )
            if isinstance(edge.target, MemoryStrandLinkTarget):
                if (
                    edge.target.web.slug == slug
                    and edge.target.strand.slug in rendered_slugs
                ):
                    continue  # already rendered in this section
                if edge.inline and edge.target.web.slug != slug:
                    cross_web_pending.append((edge.strand, edge.target, edge.link))
                    continue
                # A same-web inline link that depth truncated lists as a reference.
            elif edge.inline and isinstance(edge.target, MemoryNoteLinkTarget):
                cross_note_pending.append(edge.target)
                continue
            key = _link_target_key(edge.target)
            if key in seen_link_keys:
                continue
            seen_link_keys.add(key)
            resolved_links.append(edge.target)

        nodes = tuple(
            _closure_node(
                node,
                strand_by_index,
                scoped.origins,
                links=tuple(node_links.get(strand_by_index[node.entry.index].slug, ())),
            )
            for node in closure.nodes
        )

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
    seen_note_paths: set[str] = set(rendered_note_keys)
    for note_target in cross_note_pending:
        target_keys = _note_target_keys(note_target)
        if target_keys & seen_note_paths:
            continue
        note = _resolve_extra_note(
            note_target,
            project_root=project_root,
            home_root=home_root,
            project_name=project_name,
            notes=notes,
            scoped_webs=scoped_webs,
            depth=depth,
            seen_note_paths=frozenset(seen_note_paths | set(target_keys)),
            note_inline_context=note_inline_context,
        )
        if note is None:
            continue
        note = replace(note, render_origin="related")
        note_keys = _note_tree_keys(note)
        if note_keys & seen_note_paths:
            continue
        seen_note_paths.update(note_keys)
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


def _apply_note_strand_roots(
    sections: tuple[MemoryWebReadSection, ...],
    roots: list[_PendingNoteStrandRoot],
    *,
    scoped_webs: tuple[ScopedMemoryWeb, ...],
) -> tuple[MemoryWebReadSection, ...]:
    """Return *sections* plus related roots from flat-note inline strand links."""
    if not roots:
        return sections
    by_slug = {scoped.slug: scoped for scoped in scoped_webs}
    merged = list(sections)
    for root in roots:
        _apply_note_strand_root(merged, by_slug, root)
    return tuple(merged)


def _apply_note_strand_root(
    sections: list[MemoryWebReadSection],
    by_slug: dict[str, ScopedMemoryWeb],
    root: _PendingNoteStrandRoot,
) -> None:
    """Add a flat-note inline strand target as an extra related root."""
    target = root.target
    node = MemoryWebReadNode(
        strand=target.strand,
        scope=target.scope,
        origin="related",
        depth=_EXTRA_ROOT_DEPTH,
        referrer=(root.source_note.relative_path, root.link.raw, "link"),
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
    depth: int | None,
    seen_note_paths: frozenset[str],
    note_inline_context: _NoteInlineContext | None,
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
            depth=depth,
            seen_note_paths=seen_note_paths,
            note_inline_context=note_inline_context,
        )
    except MemoryReadError:
        return None


def _closure_node(
    node: GlossaryClosureNode,
    strand_by_index: dict[int, MemoryStrand],
    origins: dict[str, WebStrandOrigin],
    *,
    links: tuple[_MemoryWebReadLink, ...] = (),
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
        links=links,
    )


def _render_unit_candidates(
    classified: list[_NoteSelector | _WebSelector | _StrandSelector],
    *,
    project_root: Path,
    home_root: Path,
) -> tuple[MemorySelectorBatchUnit, ...]:
    return tuple(
        MemorySelectorBatchUnit(
            "note",
            _note_selector_canonical_path(
                item,
                project_root=project_root,
                home_root=home_root,
            ),
        )
        if isinstance(item, _NoteSelector)
        else MemorySelectorBatchUnit("web", item.web_slug)
        for item in classified
    )


__all__ = [
    "MemorySelectorKind",
    "MemorySelectorBatchUnit",
    "MemoryWebReadNode",
    "MemoryWebReadSection",
    "ResolvedMemorySelectorBatch",
    "resolve_memory_selector_batch",
]
