"""Selector classification and batch resolution for ``memory read``/``show``.

``sase memory read``/``show`` accept three selector shapes in one variadic
batch: a flat note name (``foo.md``), a bare memory-web name (``glossary``,
every strand), and a ``web:keyword`` strand reference. The whole batch is
resolved before any output is produced or audit event written, so one
unknown selector fails the entire request with no partial output.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from sase.main.init_memory.config import project_memory_name
from sase.memory.cli_common import MemoryCliProjectError, resolve_memory_cli_project
from sase.memory.notes import discover_memory_notes
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
    WebScope,
    WebStrandOrigin,
    discover_scoped_memory_webs,
    resolve_memory_strand,
    resolve_strand_closure,
)
from sase.memory.web.resolution import GlossaryClosureNode

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
class MemoryWebReadNode:
    """One strand printed as part of a resolved web section."""

    strand: MemoryStrand
    scope: WebScope
    origin: Literal["requested", "related"]
    depth: int
    referrer: tuple[str, str] | None
    also_referenced_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemoryWebReadSection:
    """Every strand read from one web in a batch, in closure order."""

    web: MemoryWeb
    nodes: tuple[MemoryWebReadNode, ...]
    depth_limit: int | None
    truncated: bool


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

    notes = tuple(
        _resolve_note_selector(
            item,
            project_root=project_root,
            home_root=resolved_home_root,
            project_name=project_name,
        )
        for item in classified
        if isinstance(item, _NoteSelector)
    )

    web_sections = _resolve_web_sections(
        classified,
        project_root=project_root,
        home_root=resolved_home_root,
        depth=depth,
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


def _resolve_note_selector(
    item: _NoteSelector,
    *,
    project_root: Path,
    home_root: Path,
    project_name: str,
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
    return ResolvedMemoryNote(
        content=content,
        children=children,
        origin=origin,
        project_name=project_name,
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


def _resolve_web_sections(
    classified: list[_NoteSelector | _WebSelector | _StrandSelector],
    *,
    project_root: Path,
    home_root: Path,
    depth: int | None,
) -> tuple[MemoryWebReadSection, ...]:
    web_items = [
        item for item in classified if isinstance(item, (_WebSelector, _StrandSelector))
    ]
    if not web_items:
        return ()

    scoped_webs = discover_scoped_memory_webs(project_root, home_root)
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
    for slug in order:
        scoped = by_slug[slug]
        merged_web = replace(scoped.web, strands=scoped.strands)
        wanted = requested_slugs[slug]
        roots = tuple(strand for strand in scoped.strands if strand.slug in wanted)
        closure, strand_by_index = resolve_strand_closure(
            merged_web, scoped.strands, roots, depth=depth
        )
        nodes = tuple(
            _closure_node(node, strand_by_index, scoped.origins)
            for node in closure.nodes
        )
        sections.append(
            MemoryWebReadSection(
                web=merged_web,
                nodes=nodes,
                depth_limit=closure.depth_limit,
                truncated=closure.truncated,
            )
        )
    return tuple(sections)


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
            else (node.referrer.term, node.referrer.matched_text)
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
