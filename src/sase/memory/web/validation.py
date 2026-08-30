"""Fail-closed validation for memory webs and strands."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from sase.artifact_ref_kinds import parsable_artifact_ref_kinds
from sase.core.glossary_facade import GlossaryInputEntry, validate_glossary_entries
from sase.memory.notes import (
    MemoryLinkReference,
    MemoryNote,
    discover_memory_notes,
    parse_memory_link_reference,
    parse_memory_link_rendering,
)

from .discovery import discover_memory_webs
from .lookup import normalize_memory_web_reference
from .models import (
    MemoryStrand,
    MemoryWeb,
    MemoryWebDiscovery,
    MemoryWebValidationReport,
    ScopedMemoryWeb,
)
from .roster import roster_region_error
from .scope import merge_memory_web_scopes

if TYPE_CHECKING:
    from sase.memory.link_resolve import UnresolvedMemoryLinkTarget

_STATIC_RESERVED_WEB_NAMES = frozenset({"assets", "README"})


def reserved_memory_web_names() -> frozenset[str]:
    """Return reserved web names from artifact kinds plus memory-root names."""

    return frozenset(parsable_artifact_ref_kinds()) | _STATIC_RESERVED_WEB_NAMES


def validate_memory_webs(
    discovery: MemoryWebDiscovery,
    *,
    reserved_names: frozenset[str] | None = None,
) -> MemoryWebValidationReport:
    """Validate one provider discovery result."""

    blockers: list[str] = [issue.message for issue in discovery.issues]
    resolved_reserved = (
        reserved_memory_web_names() if reserved_names is None else reserved_names
    )
    reserved_keys = {normalize_memory_web_reference(name) for name in resolved_reserved}

    for web in discovery.webs:
        if normalize_memory_web_reference(web.slug) in reserved_keys:
            blockers.append(f"{web.path}: memory web name {web.slug!r} is reserved")
        if web.source == "file":
            strand_dir = web.memory_root / web.slug
            if not strand_dir.exists() or not strand_dir.is_dir():
                blockers.append(
                    f"{web.path}: memory web descriptor has no strand directory"
                )
        marker_error = roster_region_error(web.body)
        if marker_error is not None:
            blockers.append(f"{web.path}: {marker_error}")
        blockers.extend(_strand_summary_blockers(web))
        blockers.extend(_local_label_collision_blockers(web))
        blockers.extend(_glossary_validation_blockers(web))

    return MemoryWebValidationReport(
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=_unresolved_web_link_warnings(discovery),
    )


def _strand_summary_blockers(web: MemoryWeb) -> tuple[str, ...]:
    if web.roster != "list":
        return ()
    return tuple(
        f"{strand.path}: summary is required for roster: list"
        for strand in web.strands
        if not strand.summary
    )


def _labels_for_collision(strand: MemoryStrand) -> tuple[tuple[str, str], ...]:
    labels = (
        ("slug", strand.slug),
        ("keyword", strand.keyword),
        *(("alias", alias) for alias in strand.aliases),
    )
    return tuple(
        (kind, normalized)
        for kind, raw in labels
        if (normalized := normalize_memory_web_reference(raw))
    )


def _local_label_collision_blockers(web: MemoryWeb) -> tuple[str, ...]:
    blockers: list[str] = []
    labels_by_key: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for strand in web.strands:
        for kind, label in _labels_for_collision(strand):
            labels_by_key[label][strand.slug].add(kind)

    for label, strands in sorted(labels_by_key.items()):
        if len(strands) <= 1:
            continue
        choices = ", ".join(
            f"{slug} ({'/'.join(sorted(kinds))})"
            for slug, kinds in sorted(strands.items())
        )
        blockers.append(
            f"{web.path}: ambiguous normalized strand label {label!r}: {choices}"
        )
    return tuple(blockers)


def _glossary_validation_blockers(web: MemoryWeb) -> tuple[str, ...]:
    if not web.strands:
        return ()
    entries = [
        GlossaryInputEntry(
            term=strand.keyword,
            definition=strand.body,
            aliases=strand.aliases,
            source={"source_path": str(strand.path)},
        )
        for strand in web.strands
    ]
    diagnostics = validate_glossary_entries(entries)
    return tuple(
        f"{web.path}: {diagnostic.message}"
        for diagnostic in diagnostics
        if diagnostic.severity.lower() in {"error", "fatal"}
    )


def validate_memory_web_root(
    root: Path,
    *,
    source_memory_root: Path | None = None,
) -> MemoryWebValidationReport:
    """Discover and validate memory webs under one root."""

    return validate_memory_webs(
        discover_memory_webs(root, source_memory_root=source_memory_root)
    )


def memory_note_link_warnings(
    notes: Iterable[MemoryNote],
    *,
    scoped_webs: tuple[ScopedMemoryWeb, ...] = (),
) -> tuple[str, ...]:
    """Return warnings for invalid flat-note strategies and unresolved links.

    Web descriptors are skipped: their authored links are reported by
    :func:`validate_memory_webs`. Invalid ``link_reference`` /
    ``link_rendering`` values on a flat note fall back at parse time, so this
    is the surface that names the bad value.
    """

    notes_tuple = tuple(notes)
    warnings: list[str] = []
    for note in notes_tuple:
        if note.is_web_descriptor:
            continue
        path = note.source_path or note.path
        warnings.extend(_invalid_note_strategy_warnings(note, path=path))
        warnings.extend(
            _unresolved_body_link_warnings(
                path=path,
                body=note.body,
                link_reference=note.link_reference,
                notes=notes_tuple,
                scoped_webs=scoped_webs,
                source_note=note,
            )
        )
    return tuple(dict.fromkeys(warnings))


def _unresolved_web_link_warnings(discovery: MemoryWebDiscovery) -> tuple[str, ...]:
    notes = discover_memory_notes(
        discovery.root, source_memory_root=discovery.memory_root
    )
    scoped_webs = merge_memory_web_scopes(project_webs=discovery.webs)
    warnings: list[str] = []
    notes_by_relative = {note.path.as_posix(): note for note in notes}
    for web in discovery.webs:
        warnings.extend(
            _unresolved_body_link_warnings(
                path=web.path,
                body=web.body,
                link_reference=web.link_reference,
                notes=notes,
                scoped_webs=scoped_webs,
                source_note=notes_by_relative.get(web.relative_path),
            )
        )
        for strand in web.strands:
            warnings.extend(
                _unresolved_body_link_warnings(
                    path=strand.path,
                    body=strand.body,
                    link_reference=strand.link_reference,
                    notes=notes,
                    scoped_webs=scoped_webs,
                    source_strand=strand,
                )
            )
    return tuple(dict.fromkeys(warnings))


def _unresolved_body_link_warnings(
    *,
    path: Path,
    body: str,
    link_reference: MemoryLinkReference,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    source_note: MemoryNote | None = None,
    source_strand: MemoryStrand | None = None,
) -> tuple[str, ...]:
    if link_reference == "none":
        return ()
    # Imported lazily: ``sase.memory.link_resolve`` imports ``sase.memory.web``
    # submodules, and ``sase.memory.web`` imports this module.
    from sase.memory.link_resolve import (
        UnresolvedMemoryLinkTarget,
        resolve_memory_link_target,
    )
    from sase.memory.links import scan_memory_links

    warnings: list[str] = []
    seen: set[str] = set()
    for link in scan_memory_links(body):
        target = resolve_memory_link_target(
            link.target,
            notes=notes,
            scoped_webs=scoped_webs,
            source_note=source_note,
            source_strand=source_strand,
        )
        if not isinstance(target, UnresolvedMemoryLinkTarget):
            continue
        if target.raw in seen:
            continue
        seen.add(target.raw)
        warnings.append(_format_unresolved_link_warning(path, target))
    return tuple(warnings)


def _invalid_note_strategy_warnings(note: MemoryNote, *, path: Path) -> tuple[str, ...]:
    warnings: list[str] = []
    if (
        "link_reference" in note.frontmatter
        and parse_memory_link_reference(note.frontmatter.get("link_reference")) is None
    ):
        warnings.append(f"{path}: link_reference must be explicit, implicit, or none")
    if (
        "link_rendering" in note.frontmatter
        and parse_memory_link_rendering(note.frontmatter.get("link_rendering")) is None
    ):
        warnings.append(f"{path}: link_rendering must be reference or inline")
    return tuple(warnings)


def _format_unresolved_link_warning(
    path: Path, target: UnresolvedMemoryLinkTarget
) -> str:
    token = f"[[{target.raw}]]"
    if target.candidates:
        suggestions = ", ".join(target.candidates)
        return f"{path}: unresolved memory link {token} (did you mean {suggestions})"
    return f"{path}: unresolved memory link {token}"


__all__ = [
    "memory_note_link_warnings",
    "reserved_memory_web_names",
    "validate_memory_web_root",
    "validate_memory_webs",
]
