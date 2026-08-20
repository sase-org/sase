"""ACE snippets panel catalog service: project ring and per-project snapshots.

Python owns disk work and caching here; Rust composition stays behind the
shared catalog loader. The ring build and snapshot loads in this module must
only ever run off the event loop -- see the TUI performance rules.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from sase.config.core import current_config_token
from sase.content_layout import resolve_project_config_read_path
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.snippet.catalog import load_snippet_catalog
from sase.snippet.models import SnippetCatalog, SnippetEntry
from sase.xprompt.glossary_catalog import (
    enabled_project_records,
    glossary_project_record_for_workspace,
)
from sase.xprompt.snippet_config_yaml import snippet_config_digest
from sase.xprompt.snippet_targets import load_snippet_config_locations

_MAX_SNAPSHOT_CACHE_PROJECTS = 8
_MIN_RESTAT_INTERVAL_S = 0.5


@dataclass(frozen=True, slots=True)
class SnippetProjectRef:
    """One project's identity in the snippets panel's ring."""

    key: str
    display_name: str
    workspace_dir: str


@dataclass(frozen=True, slots=True)
class SnippetDestination:
    """One writable YAML destination the add/edit form can cycle through."""

    label: str
    path: str
    display_path: str
    digest: str = ""
    selectable: bool = True


@dataclass(frozen=True, slots=True)
class SnippetProjectSnapshot:
    """A loaded (or best-effort failed) snippet catalog for one project."""

    project: SnippetProjectRef
    catalog: SnippetCatalog | None
    diagnostics: tuple[str, ...]
    destinations: tuple[SnippetDestination, ...] = ()
    default_destination_path: str | None = None


@dataclass
class _SnapshotCacheEntry:
    snapshot: SnippetProjectSnapshot
    config_mtime_ns: int
    config_size: int
    config_token: tuple[Any, ...]
    last_checked_monotonic: float


_snapshot_cache: OrderedDict[str, _SnapshotCacheEntry] = OrderedDict()


def build_snippet_project_ring(
    launch_workspace: str | Path | None = None,
    *,
    projects_root: str | Path | None = None,
) -> tuple[SnippetProjectRef, ...]:
    """Return the ordered, de-duplicated project ring for ``p``/``P`` cycling.

    Every enabled project is included because xprompt-derived snippets exist
    without an ``ace.snippets`` section. The launch workspace's project is
    always kept even when it is not already in the enabled set, so browsing
    can still seed from the panel's opening context. Order is by display
    name. One broken project must never shrink the ring for everyone else.
    """
    records = enabled_project_records(projects_root)
    launch_record = glossary_project_record_for_workspace(launch_workspace, records)

    refs: dict[str, SnippetProjectRef] = {}
    for record in records:
        refs[record.project_name] = _project_ref(record)

    if launch_record is not None and launch_record.project_name not in refs:
        refs[launch_record.project_name] = _project_ref(launch_record)

    return tuple(
        sorted(refs.values(), key=lambda ref: (ref.display_name.casefold(), ref.key))
    )


def load_snippet_project_snapshot(ref: SnippetProjectRef) -> SnippetProjectSnapshot:
    """Load *ref*'s snippet catalog behind an mtime/token-keyed LRU.

    Only ever call this off the event loop: a cache miss composes xprompt
    snippets and config layers through the shared catalog service.
    """
    now = time.monotonic()
    current_stat = _config_stat(ref)
    current_token = _config_token()
    cached = _snapshot_cache.get(ref.key)
    if cached is not None:
        recent = (now - cached.last_checked_monotonic) < _MIN_RESTAT_INTERVAL_S
        same = current_stat == (cached.config_mtime_ns, cached.config_size) and (
            current_token == cached.config_token
        )
        if recent or same:
            cached.last_checked_monotonic = now
            _snapshot_cache.move_to_end(ref.key)
            return cached.snapshot

    snapshot = _load_snippet_project_snapshot(ref)
    _snapshot_cache[ref.key] = _SnapshotCacheEntry(
        snapshot=snapshot,
        config_mtime_ns=current_stat[0],
        config_size=current_stat[1],
        config_token=current_token,
        last_checked_monotonic=now,
    )
    _snapshot_cache.move_to_end(ref.key)
    while len(_snapshot_cache) > _MAX_SNAPSHOT_CACHE_PROJECTS:
        _snapshot_cache.popitem(last=False)
    return snapshot


def invalidate_snippet_project(key: str) -> None:
    """Drop *key*'s cached snapshot, e.g. after a later panel write."""
    _snapshot_cache.pop(key, None)


def snippet_entry_relations(
    snapshot: SnippetProjectSnapshot, entry: SnippetEntry
) -> tuple[tuple[SnippetEntry, ...], tuple[SnippetEntry, ...]]:
    """Return the ordered (outbound, inbound) entries the card can follow.

    Alias calls already land on the canonical explicit trigger in the shared
    catalog's outbound index. Missing and cyclic calls are omitted here so
    travel never follows a diagnostic.
    """
    if snapshot.catalog is None:
        return (), ()
    by_trigger = {
        candidate.trigger: candidate for candidate in snapshot.catalog.entries
    }
    outbound = tuple(
        by_trigger[trigger]
        for trigger in entry.relations.outbound
        if trigger in by_trigger
    )
    inbound = tuple(
        by_trigger[trigger]
        for trigger in entry.relations.inbound
        if trigger in by_trigger
    )
    return outbound, inbound


def _project_ref(record: ProjectRecordWire) -> SnippetProjectRef:
    return SnippetProjectRef(
        key=record.project_name,
        display_name=effective_project_name(record),
        workspace_dir=str(record.workspace_dir or ""),
    )


def _resolve_config_path(project_key: str, workspace_dir: str) -> Path | None:
    try:
        return resolve_project_config_read_path(
            Path(workspace_dir),
            label=f"project config for {project_key}",
        )
    except Exception:
        return None


def _config_stat(ref: SnippetProjectRef) -> tuple[int, int]:
    if not ref.workspace_dir:
        return (0, 0)
    config_path = _resolve_config_path(ref.key, ref.workspace_dir)
    if config_path is None:
        return (0, 0)
    try:
        stat = config_path.stat()
    except OSError:
        return (0, 0)
    return (stat.st_mtime_ns, stat.st_size)


def _config_token() -> tuple[Any, ...]:
    try:
        return current_config_token()
    except Exception:
        return ()


def _load_snippet_project_snapshot(ref: SnippetProjectRef) -> SnippetProjectSnapshot:
    destinations, default_destination_path = _snapshot_destinations(ref)
    try:
        catalog = load_snippet_catalog(
            ref.key,
            launch_workspace=ref.workspace_dir or None,
        )
    except Exception as exc:
        return SnippetProjectSnapshot(
            project=ref,
            catalog=None,
            diagnostics=(f"{ref.display_name}: failed to load snippets: {exc}",),
            destinations=destinations,
            default_destination_path=default_destination_path,
        )
    diagnostics = tuple(
        _format_layer_diagnostic(item) for item in catalog.layer_diagnostics
    )
    destinations = _merge_contribution_destinations(destinations, catalog)
    return SnippetProjectSnapshot(
        project=ref,
        catalog=catalog,
        diagnostics=diagnostics,
        destinations=destinations,
        default_destination_path=default_destination_path,
    )


def _snapshot_destinations(
    ref: SnippetProjectRef,
) -> tuple[tuple[SnippetDestination, ...], str | None]:
    """Discover writable YAML destinations and hash each selectable file."""
    try:
        locations = load_snippet_config_locations(
            ref.key, launch_workspace=ref.workspace_dir or None
        )
    except Exception:
        return (), None
    destinations: list[SnippetDestination] = []
    default_path: str | None = None
    for location in locations:
        digest = _path_digest(location.path) if location.is_selectable else ""
        destinations.append(
            SnippetDestination(
                label=location.label,
                path=location.path,
                display_path=location.display_path,
                digest=digest,
                selectable=location.is_selectable,
            )
        )
        if default_path is None and location.is_selectable:
            default_path = location.path
    return tuple(destinations), default_path


def _merge_contribution_destinations(
    destinations: tuple[SnippetDestination, ...],
    catalog: SnippetCatalog,
) -> tuple[SnippetDestination, ...]:
    """Include writable contribution paths that discovery did not list."""
    seen = {item.path for item in destinations}
    extra: list[SnippetDestination] = []
    for entry in catalog.entries:
        for contribution in entry.contributions:
            path = contribution.path
            if not path or not contribution.writable or path in seen:
                continue
            extra.append(
                SnippetDestination(
                    label=contribution.kind,
                    path=path,
                    display_path=contribution.display_path or path,
                    digest=_path_digest(path),
                    selectable=True,
                )
            )
            seen.add(path)
    if not extra:
        return destinations
    return (*destinations, *extra)


def _path_digest(path: str) -> str:
    file_path = Path(path)
    try:
        data = file_path.read_bytes() if file_path.is_file() else b""
    except OSError:
        data = b""
    return snippet_config_digest(data)


def _format_layer_diagnostic(item: Any) -> str:
    message = getattr(item, "message", str(item))
    path = getattr(item, "path", None)
    if path:
        return f"{path}: {message}"
    return str(message)


__all__ = [
    "SnippetDestination",
    "SnippetProjectRef",
    "SnippetProjectSnapshot",
    "build_snippet_project_ring",
    "invalidate_snippet_project",
    "load_snippet_project_snapshot",
    "snippet_entry_relations",
]
