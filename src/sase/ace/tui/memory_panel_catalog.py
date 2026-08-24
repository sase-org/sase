"""ACE memory panel catalog service: scope ring and per-scope snapshots.

Python owns disk work and caching here; memory-note parsing stays in
``sase.memory``. The ring build and snapshot loads in this module must only
ever run off the event loop -- see the TUI performance rules.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
import time
from typing import Literal

from sase.config import CHEZMOI_HOME, get_use_chezmoi
from sase.content_layout import LayoutCollisionError, resolve_memory_file_sources
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.main.init_memory.config import project_memory_name
from sase.main.init_memory.root_rendering import generated_memory_note_relative_paths
from sase.memory.inventory import MemoryStats, stats_for_text
from sase.memory.notes import (
    AGENTS_PARENT,
    README_FILENAME,
    MemoryNote,
    discover_memory_notes,
)
from sase.memory.paths import memory_read_root
from sase.memory.read_log import (
    MemoryReadPathSummary,
    read_memory_read_events,
    summarize_memory_reads_by_path,
)
from sase.memory.web.discovery import discover_memory_webs
from sase.memory.web.models import MemoryStrand, MemoryWeb, WebScope
from sase.xprompt.glossary_catalog import (
    enabled_project_records,
    glossary_project_record_for_workspace,
)

_MAX_SNAPSHOT_CACHE_SCOPES = 8
_MIN_RESTAT_INTERVAL_S = 0.5
_HOME_SCOPE_KEY = "home"


@dataclass(frozen=True, slots=True)
class MemoryScopeRef:
    """One memory-bearing content root in the panel's scope ring."""

    kind: Literal["project", "home"]
    key: str
    display_name: str
    content_root: str
    memory_read_root: str | None
    has_memory: bool


@dataclass(frozen=True, slots=True)
class MemoryNoteDigest:
    """Stale-write guard for one note: mtime, size, and content hash."""

    mtime_ns: int
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class MemoryRailNode:
    """One row in the panel's rail, with tree indent depth."""

    note: MemoryNote
    depth: int
    web: MemoryWeb | None = None
    strand: MemoryStrand | None = None
    strand_scope: WebScope | None = None
    expanded: bool = False

    @property
    def identity(self) -> str:
        """Return the stable selection identity for this rail row."""
        if self.strand is not None:
            return f"{self.strand.web_slug}:{self.strand.slug}"
        return self.note.relative_path

    @property
    def is_web(self) -> bool:
        """Return whether this row is a web descriptor row."""
        return self.web is not None and self.strand is None

    @property
    def is_strand(self) -> bool:
        """Return whether this row previews one web strand."""
        return self.strand is not None


@dataclass(frozen=True, slots=True)
class MemoryScopeSnapshot:
    """A loaded (or best-effort failed) memory-note catalog for one scope."""

    scope: MemoryScopeRef
    notes: tuple[MemoryNote, ...]
    tree: tuple[MemoryRailNode, ...]
    digests: Mapping[str, MemoryNoteDigest]
    stats: Mapping[str, MemoryStats]
    shadowed_stems: frozenset[str]
    generated_paths: frozenset[str]
    read_summaries: Mapping[str, MemoryReadPathSummary]
    diagnostics: tuple[str, ...]
    webs: tuple[MemoryWeb, ...] = ()


@dataclass
class _SnapshotCacheEntry:
    snapshot: MemoryScopeSnapshot
    dir_mtime_ns: int
    dir_size: int
    note_stats: tuple[tuple[str, int, int], ...]
    last_checked_monotonic: float


_snapshot_cache: OrderedDict[str, _SnapshotCacheEntry] = OrderedDict()


def build_memory_scope_ring(
    launch_workspace: str | Path | None = None,
    *,
    projects_root: str | Path | None = None,
) -> tuple[MemoryScopeRef, ...]:
    """Return the ordered, de-duplicated scope ring for ``p``/``P`` cycling.

    Every enabled project whose content root resolves a memory read root is
    included, plus the project the panel was opened from even when it has
    none, so ``a`` can bootstrap that project's first note. Project scopes
    sort by display name; the Home scope is always last.
    """
    records = enabled_project_records(projects_root)
    launch_record = glossary_project_record_for_workspace(launch_workspace, records)

    refs: dict[str, MemoryScopeRef] = {}
    for record in records:
        ref = _project_scope_ref(record)
        if ref.has_memory:
            refs[record.project_name] = ref

    if launch_record is not None and launch_record.project_name not in refs:
        refs[launch_record.project_name] = _project_scope_ref(launch_record)

    projects = tuple(
        sorted(refs.values(), key=lambda ref: (ref.display_name.casefold(), ref.key))
    )
    return (*projects, _home_scope_ref())


def load_memory_scope_snapshot(ref: MemoryScopeRef) -> MemoryScopeSnapshot:
    """Load *ref*'s notes behind an mtime-keyed cache.

    Only ever call this off the event loop: a cache miss reads the scope's
    memory directory and every note file.
    """
    now = time.monotonic()
    current_stat = _scope_stat(ref)
    cached = _snapshot_cache.get(ref.key)
    if cached is not None:
        recent = (now - cached.last_checked_monotonic) < _MIN_RESTAT_INTERVAL_S
        cached_stat = (cached.dir_mtime_ns, cached.dir_size, cached.note_stats)
        if recent or current_stat == cached_stat:
            cached.last_checked_monotonic = now
            _snapshot_cache.move_to_end(ref.key)
            return cached.snapshot

    snapshot = _load_memory_scope_snapshot(ref)
    _snapshot_cache[ref.key] = _SnapshotCacheEntry(
        snapshot=snapshot,
        dir_mtime_ns=current_stat[0],
        dir_size=current_stat[1],
        note_stats=current_stat[2],
        last_checked_monotonic=now,
    )
    _snapshot_cache.move_to_end(ref.key)
    while len(_snapshot_cache) > _MAX_SNAPSHOT_CACHE_SCOPES:
        _snapshot_cache.popitem(last=False)
    return snapshot


def invalidate_memory_scope(key: str) -> None:
    """Drop *key*'s cached snapshot, e.g. after a panel write."""
    _snapshot_cache.pop(key, None)


def memory_note_relations(
    snapshot: MemoryScopeSnapshot, note: MemoryNote
) -> tuple[tuple[MemoryNote, ...], tuple[MemoryNote, ...]]:
    """Return the ordered ``(parent, children)`` notes the card renders.

    An ``AGENTS.md`` parent yields no parent chip. Missing or invalid parents
    likewise yield an empty parent tuple so the card never invents an edge.
    """
    by_path = {item.relative_path: item for item in snapshot.notes}
    parent: tuple[MemoryNote, ...] = ()
    if note.parent != AGENTS_PARENT:
        parent_note = by_path.get(note.parent)
        if parent_note is not None:
            parent = (parent_note,)
    children = tuple(
        sorted(
            (
                item
                for item in snapshot.notes
                if item.type == "reference" and item.parent == note.relative_path
            ),
            key=lambda item: item.relative_path,
        )
    )
    return parent, children


def memory_strand_note(web: MemoryWeb, strand: MemoryStrand) -> MemoryNote:
    """Return the pseudo-note used to render and source one strand row."""
    description_parts = []
    if strand.summary:
        description_parts.append(strand.summary)
    if strand.aliases:
        description_parts.append("Aliases: " + ", ".join(strand.aliases))
    return MemoryNote(
        path=Path(f"{web.slug}:{strand.slug}"),
        type=web.rendering_type,
        parent=web.relative_path,
        description=" ".join(description_parts) or None,
        body=strand.body,
        frontmatter=strand.frontmatter,
        type_source="frontmatter",
        parent_source="frontmatter",
        source_path=Path(strand.relative_path),
    )


def _home_content_root() -> Path:
    if get_use_chezmoi():
        return Path(CHEZMOI_HOME)
    return Path.home()


def _home_display_name() -> str:
    return "Home (chezmoi)" if get_use_chezmoi() else "Home"


def _home_scope_ref() -> MemoryScopeRef:
    content_root = _home_content_root()
    read_root, has_memory = _content_root_memory(content_root, label="home memory")
    return MemoryScopeRef(
        kind="home",
        key=_HOME_SCOPE_KEY,
        display_name=_home_display_name(),
        content_root=str(content_root),
        memory_read_root=None if read_root is None else str(read_root),
        has_memory=has_memory,
    )


def _project_scope_ref(record: ProjectRecordWire) -> MemoryScopeRef:
    content_root = Path(record.workspace_dir or "")
    label = f"memory for {record.project_name}"
    read_root, has_memory = _content_root_memory(content_root, label=label)
    return MemoryScopeRef(
        kind="project",
        key=record.project_name,
        display_name=effective_project_name(record),
        content_root=str(content_root),
        memory_read_root=None if read_root is None else str(read_root),
        has_memory=has_memory,
    )


def _content_root_memory(content_root: Path, *, label: str) -> tuple[Path | None, bool]:
    """Return ``(read_root, has_memory)`` for *content_root*.

    A canonical/legacy collision still counts as having memory so the scope
    stays in the ring and snapshot load can surface the diagnostic.
    """
    if not content_root:
        return None, False
    try:
        read_root = memory_read_root(content_root, label=label)
    except LayoutCollisionError:
        return None, True
    except OSError:
        return None, False
    return read_root, read_root is not None


def _resolve_scope_memory_root(ref: MemoryScopeRef) -> Path | None:
    if ref.kind == "home":
        sources = resolve_memory_file_sources(
            project_root=None,
            home_root=ref.content_root,
            include_discovered_project=False,
        )
        for source in sources:
            if source.scope == "home":
                return source.resolve_read_root("home memory")
    else:
        sources = resolve_memory_file_sources(
            project_root=ref.content_root,
            project=ref.key,
            include_discovered_project=False,
        )
        for source in sources:
            if source.scope == "project":
                return source.resolve_read_root(f"memory for {ref.key}")
    if not ref.content_root:
        return None
    return memory_read_root(Path(ref.content_root), label=f"{ref.kind} memory")


def _scope_stat(
    ref: MemoryScopeRef,
) -> tuple[int, int, tuple[tuple[str, int, int], ...]]:
    try:
        memory_root = _resolve_scope_memory_root(ref)
    except LayoutCollisionError:
        return (-1, -1, ())
    except OSError:
        return (0, 0, ())
    if memory_root is None:
        return (0, 0, ())
    try:
        dir_stat = memory_root.stat()
    except OSError:
        return (0, 0, ())
    note_stats: list[tuple[str, int, int]] = []
    try:
        for path in sorted(memory_root.rglob("*.md")):
            if not path.is_file() or path.name == README_FILENAME:
                continue
            try:
                file_stat = path.stat()
            except OSError:
                continue
            note_stats.append(
                (
                    path.relative_to(memory_root).as_posix(),
                    file_stat.st_mtime_ns,
                    file_stat.st_size,
                )
            )
    except OSError:
        return (dir_stat.st_mtime_ns, dir_stat.st_size, ())
    return (dir_stat.st_mtime_ns, dir_stat.st_size, tuple(note_stats))


def _load_memory_scope_snapshot(ref: MemoryScopeRef) -> MemoryScopeSnapshot:
    generated_paths = frozenset(
        path.as_posix()
        for path in generated_memory_note_relative_paths(
            include_project_memory=ref.kind == "project"
        )
    )
    try:
        memory_root = _resolve_scope_memory_root(ref)
    except (LayoutCollisionError, OSError) as exc:
        return _empty_snapshot(ref, generated_paths, diagnostics=(str(exc),))
    if memory_root is None:
        return _empty_snapshot(ref, generated_paths)

    content_root = Path(ref.content_root)
    try:
        notes = discover_memory_notes(content_root, source_memory_root=memory_root)
    except (OSError, UnicodeDecodeError) as exc:
        return _empty_snapshot(ref, generated_paths, diagnostics=(str(exc),))

    webs: tuple[MemoryWeb, ...] = ()
    diagnostics: tuple[str, ...] = ()
    try:
        discovery = discover_memory_webs(
            content_root,
            source_memory_root=memory_root,
        )
    except (OSError, UnicodeDecodeError) as exc:
        diagnostics = (str(exc),)
    else:
        webs = discovery.webs
        diagnostics = tuple(issue.message for issue in discovery.issues)

    digests, stats = _memory_file_metadata(content_root, notes, webs)
    return MemoryScopeSnapshot(
        scope=ref,
        notes=notes,
        tree=_build_note_tree(notes, webs),
        digests=digests,
        stats=stats,
        shadowed_stems=_shadowed_stems_for(ref, notes),
        generated_paths=generated_paths,
        read_summaries=_read_summaries_for(ref),
        diagnostics=diagnostics,
        webs=webs,
    )


def _empty_snapshot(
    ref: MemoryScopeRef,
    generated_paths: frozenset[str],
    *,
    diagnostics: tuple[str, ...] = (),
) -> MemoryScopeSnapshot:
    return MemoryScopeSnapshot(
        scope=ref,
        notes=(),
        tree=(),
        digests={},
        stats={},
        shadowed_stems=frozenset(),
        generated_paths=generated_paths,
        read_summaries={},
        diagnostics=diagnostics,
        webs=(),
    )


def _memory_file_metadata(
    content_root: Path, notes: tuple[MemoryNote, ...], webs: tuple[MemoryWeb, ...]
) -> tuple[dict[str, MemoryNoteDigest], dict[str, MemoryStats]]:
    digests: dict[str, MemoryNoteDigest] = {}
    stats: dict[str, MemoryStats] = {}
    for note in notes:
        _add_file_metadata(content_root, note, digests, stats)
    for web in webs:
        for strand in web.strands:
            _add_file_metadata(
                content_root,
                memory_strand_note(web, strand),
                digests,
                stats,
            )
    return digests, stats


def _add_file_metadata(
    content_root: Path,
    note: MemoryNote,
    digests: dict[str, MemoryNoteDigest],
    stats: dict[str, MemoryStats],
) -> None:
    path = content_root / note.source_relative_path
    try:
        data = path.read_bytes()
        file_stat = path.stat()
    except OSError:
        return
    digests[note.relative_path] = MemoryNoteDigest(
        mtime_ns=file_stat.st_mtime_ns,
        size=file_stat.st_size,
        sha256=hashlib.sha256(data).hexdigest(),
    )
    stats[note.relative_path] = stats_for_text(data.decode("utf-8", errors="replace"))


def _build_note_tree(
    notes: tuple[MemoryNote, ...], webs: tuple[MemoryWeb, ...] = ()
) -> tuple[MemoryRailNode, ...]:
    """Order notes as Tier 1, then Tier 2 roots with children indented once."""
    emitted: set[str] = set()
    tree: list[MemoryRailNode] = []
    webs_by_path = {web.relative_path: web for web in webs}
    children_by_parent: dict[str, list[MemoryNote]] = {}
    for note in notes:
        if note.type == "reference":
            children_by_parent.setdefault(note.parent, []).append(note)
    for children in children_by_parent.values():
        children.sort(key=lambda note: note.relative_path)

    def emit_root(root: MemoryNote) -> None:
        tree.append(_rail_node_for_note(root, depth=0, webs_by_path=webs_by_path))
        emitted.add(root.relative_path)
        for child in children_by_parent.get(root.relative_path, ()):
            tree.append(_rail_node_for_note(child, depth=1, webs_by_path=webs_by_path))
            emitted.add(child.relative_path)

    shorts = sorted(
        (note for note in notes if note.type == "core"),
        key=lambda note: note.relative_path,
    )
    for note in shorts:
        tree.append(_rail_node_for_note(note, depth=0, webs_by_path=webs_by_path))
        emitted.add(note.relative_path)

    long_roots = sorted(
        (
            note
            for note in notes
            if note.type == "reference" and note.parent == AGENTS_PARENT
        ),
        key=lambda note: note.relative_path,
    )
    for note in long_roots:
        emit_root(note)

    leftover_long = sorted(
        (
            note
            for note in notes
            if note.type == "reference" and note.relative_path not in emitted
        ),
        key=lambda note: note.relative_path,
    )
    leftover_paths = {note.relative_path for note in leftover_long}
    leftover_roots = [
        note for note in leftover_long if note.parent not in leftover_paths
    ]
    for note in leftover_roots:
        emit_root(note)
    for note in leftover_long:
        if note.relative_path not in emitted:
            tree.append(_rail_node_for_note(note, depth=0, webs_by_path=webs_by_path))
            emitted.add(note.relative_path)

    for note in sorted(notes, key=lambda item: item.relative_path):
        if note.relative_path not in emitted:
            tree.append(_rail_node_for_note(note, depth=0, webs_by_path=webs_by_path))
            emitted.add(note.relative_path)
    return tuple(tree)


def _rail_node_for_note(
    note: MemoryNote, *, depth: int, webs_by_path: dict[str, MemoryWeb]
) -> MemoryRailNode:
    return MemoryRailNode(
        note=note, depth=depth, web=webs_by_path.get(note.relative_path)
    )


def _shadowed_stems_for(
    ref: MemoryScopeRef, notes: tuple[MemoryNote, ...]
) -> frozenset[str]:
    if ref.kind != "project" or not notes:
        return frozenset()
    home_stems = _discover_home_stems()
    if not home_stems:
        return frozenset()
    return frozenset(note.path.stem for note in notes if note.path.stem in home_stems)


def _discover_home_stems() -> frozenset[str]:
    home_ref = _home_scope_ref()
    try:
        memory_root = _resolve_scope_memory_root(home_ref)
    except (LayoutCollisionError, OSError):
        return frozenset()
    if memory_root is None:
        return frozenset()
    try:
        notes = discover_memory_notes(
            Path(home_ref.content_root), source_memory_root=memory_root
        )
    except (OSError, UnicodeDecodeError):
        return frozenset()
    return frozenset(note.path.stem for note in notes)


def _read_summaries_for(ref: MemoryScopeRef) -> dict[str, MemoryReadPathSummary]:
    if not ref.content_root:
        return {}
    try:
        project_name = project_memory_name(Path(ref.content_root))
        events = read_memory_read_events(project=project_name)
    except Exception:  # noqa: BLE001 - a missing log must not sink the snapshot.
        return {}
    summaries: dict[str, MemoryReadPathSummary] = {}
    for summary in summarize_memory_reads_by_path(events):
        summaries[summary.canonical_path] = summary
    return summaries


__all__ = [
    "MemoryNoteDigest",
    "MemoryRailNode",
    "MemoryScopeRef",
    "MemoryScopeSnapshot",
    "build_memory_scope_ring",
    "invalidate_memory_scope",
    "load_memory_scope_snapshot",
    "memory_strand_note",
    "memory_note_relations",
]
