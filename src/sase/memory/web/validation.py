"""Fail-closed validation for memory webs and strands."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from sase.artifact_ref_kinds import parsable_artifact_ref_kinds
from sase.core.glossary_facade import GlossaryInputEntry, validate_glossary_entries

from .discovery import discover_memory_webs
from .lookup import normalize_memory_web_reference
from .models import (
    MemoryStrand,
    MemoryWeb,
    MemoryWebDiscovery,
    MemoryWebValidationReport,
)
from .roster import roster_region_error

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
        warnings=(),
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


__all__ = [
    "reserved_memory_web_names",
    "validate_memory_web_root",
    "validate_memory_webs",
]
