"""ACE glossary panel catalog service: project ring and per-project snapshots.

Python owns disk work and caching here; the Rust glossary validator and
matcher stay untouched. The ring build and snapshot loads in this module
must only ever run off the event loop -- see the TUI performance rules.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import time

from sase.ace.tui.modals.glossary_preview_render import glossary_cross_references
from sase.core.glossary_facade import GlossaryEntry
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.memory.web.relations import glossary_reverse_references
from sase.memory.web.catalog import (
    GLOSSARY_WEB_SLUG,
    find_memory_web,
    memory_web_source_signature,
)
from sase.xprompt.glossary_catalog import (
    EditorGlossaryCatalog,
    editor_glossary_catalog_for_project,
    enabled_project_records,
    glossary_project_record_for_workspace,
)

_MAX_SNAPSHOT_CACHE_PROJECTS = 8
_MIN_RESTAT_INTERVAL_S = 0.5


@dataclass(frozen=True, slots=True)
class GlossaryProjectRef:
    """One project's identity and glossary presence in the panel's ring."""

    key: str
    display_name: str
    workspace_dir: str
    has_glossary: bool


@dataclass(frozen=True, slots=True)
class GlossaryProjectSnapshot:
    """A loaded (or best-effort failed) glossary catalog for one project."""

    project: GlossaryProjectRef
    catalog: EditorGlossaryCatalog | None
    reverse_references: Mapping[int, tuple[str, ...]]
    diagnostics: tuple[str, ...]


@dataclass
class _SnapshotCacheEntry:
    snapshot: GlossaryProjectSnapshot
    config_mtime_ns: int
    config_size: int
    last_checked_monotonic: float


_snapshot_cache: OrderedDict[str, _SnapshotCacheEntry] = OrderedDict()


def build_glossary_project_ring(
    launch_workspace: str | Path | None = None,
    *,
    projects_root: str | Path | None = None,
) -> tuple[GlossaryProjectRef, ...]:
    """Return the ordered, de-duplicated project ring for `p`/`P` cycling.

    Every enabled project with a glossary memory web is included, plus the
    project the panel was opened from even when it has none. Order is by
    display name.
    """
    records = enabled_project_records(projects_root)
    launch_record = glossary_project_record_for_workspace(launch_workspace, records)

    refs: dict[str, GlossaryProjectRef] = {}
    for record in records:
        has_glossary = _project_declares_glossary(record)
        if has_glossary:
            refs[record.project_name] = _project_ref(record, has_glossary=True)

    if launch_record is not None and launch_record.project_name not in refs:
        refs[launch_record.project_name] = _project_ref(
            launch_record, has_glossary=False
        )

    return tuple(
        sorted(refs.values(), key=lambda ref: (ref.display_name.casefold(), ref.key))
    )


def load_glossary_project_snapshot(ref: GlossaryProjectRef) -> GlossaryProjectSnapshot:
    """Load and compile *ref*'s glossary catalog behind an mtime-keyed cache.

    Only ever call this off the event loop: a cache miss reads and compiles
    a project's glossary memory web.
    """
    now = time.monotonic()
    current_stat = _config_stat(ref)
    cached = _snapshot_cache.get(ref.key)
    if cached is not None:
        recent = (now - cached.last_checked_monotonic) < _MIN_RESTAT_INTERVAL_S
        if recent or current_stat == (cached.config_mtime_ns, cached.config_size):
            cached.last_checked_monotonic = now
            _snapshot_cache.move_to_end(ref.key)
            return cached.snapshot

    snapshot = _load_glossary_project_snapshot(ref)
    _snapshot_cache[ref.key] = _SnapshotCacheEntry(
        snapshot=snapshot,
        config_mtime_ns=current_stat[0],
        config_size=current_stat[1],
        last_checked_monotonic=now,
    )
    _snapshot_cache.move_to_end(ref.key)
    while len(_snapshot_cache) > _MAX_SNAPSHOT_CACHE_PROJECTS:
        _snapshot_cache.popitem(last=False)
    return snapshot


def invalidate_glossary_project(key: str) -> None:
    """Drop *key*'s cached snapshot, e.g. after a panel write."""
    _snapshot_cache.pop(key, None)


def glossary_entry_relations(
    snapshot: GlossaryProjectSnapshot, entry: GlossaryEntry
) -> tuple[tuple[GlossaryEntry, ...], tuple[GlossaryEntry, ...]]:
    """Return the ordered (outbound, inbound) relation entries the card renders."""
    if snapshot.catalog is None:
        return (), ()
    outbound = glossary_cross_references(snapshot.catalog, entry)
    by_term = {candidate.term: candidate for candidate in snapshot.catalog.entries}
    inbound = tuple(
        by_term[term]
        for term in snapshot.reverse_references.get(entry.index, ())
        if term in by_term
    )
    return outbound, inbound


def _project_ref(
    record: ProjectRecordWire, *, has_glossary: bool
) -> GlossaryProjectRef:
    return GlossaryProjectRef(
        key=record.project_name,
        display_name=effective_project_name(record),
        workspace_dir=str(record.workspace_dir or ""),
        has_glossary=has_glossary,
    )


def _project_declares_glossary(record: ProjectRecordWire) -> bool:
    """Return whether *record* has a glossary memory web."""
    if not record.workspace_dir:
        return False
    return find_memory_web(Path(record.workspace_dir), GLOSSARY_WEB_SLUG) is not None


def _config_stat(ref: GlossaryProjectRef) -> tuple[int, int]:
    if not ref.workspace_dir:
        return (0, 0)
    web = find_memory_web(Path(ref.workspace_dir), GLOSSARY_WEB_SLUG)
    if web is not None:
        signature = memory_web_source_signature(web)
        return (signature.mtime_ns, signature.size)
    return (0, 0)


def _load_glossary_project_snapshot(ref: GlossaryProjectRef) -> GlossaryProjectSnapshot:
    result = editor_glossary_catalog_for_project(
        ref.key,
        launch_workspace=ref.workspace_dir or None,
    )
    if result.catalog is None:
        return GlossaryProjectSnapshot(
            project=ref,
            catalog=None,
            reverse_references={},
            diagnostics=result.diagnostics,
        )
    reverse = glossary_reverse_references(
        result.catalog.catalog, result.catalog.compiled
    )
    return GlossaryProjectSnapshot(
        project=ref,
        catalog=result.catalog,
        reverse_references=reverse,
        diagnostics=(),
    )


__all__ = [
    "GlossaryProjectRef",
    "GlossaryProjectSnapshot",
    "build_glossary_project_ring",
    "glossary_entry_relations",
    "invalidate_glossary_project",
    "load_glossary_project_snapshot",
]
