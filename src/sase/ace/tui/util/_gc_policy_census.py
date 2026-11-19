"""Opt-in GC census: survivor types and bounded result-cache ownership."""

from __future__ import annotations

import os
import sys
from collections import Counter, OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ._gc_policy_config import CENSUS_TOP_N, ENV_CENSUS


def census_enabled() -> bool:
    """Return whether the opt-in GC census is on (``SASE_TUI_GC_CENSUS=1``)."""
    return os.environ.get(ENV_CENSUS) == "1"


def survivor_census_safe() -> bool:
    """Return whether ``gc.get_objects()`` is safe to hold during a census.

    On CPython < 3.14, ``gc.get_objects()`` exposes tuples that other threads
    are still building, and holding them makes those threads'
    ``_PyTuple_Resize`` fail with ``SystemError``.
    """
    return sys.version_info >= (3, 14)


def _type_key(obj: object) -> str:
    cls = type(obj)
    module = getattr(cls, "__module__", "") or ""
    qualname = (
        getattr(cls, "__qualname__", None) or getattr(cls, "__name__", None) or "?"
    )
    return f"{module}.{qualname}" if module else str(qualname)


@dataclass(frozen=True)
class TypeCensus:
    """Ranked type counts plus optional watchlist rows from one object walk."""

    top: list[dict[str, Any]]
    total: int
    watch: list[dict[str, Any]]
    bytes_total: int


def _type_row(name: str, count: int, size: int) -> dict[str, Any]:
    return {"type": name, "count": count, "bytes": int(size)}


def top_types(
    objects: Iterable[object],
    n: int = CENSUS_TOP_N,
    *,
    watch: frozenset[str] | None = None,
) -> TypeCensus:
    """Return the *n* most common types, watchlist rows, and shallow bytes."""
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    total = 0
    bytes_total = 0
    for obj in objects:
        total += 1
        try:
            key = _type_key(obj)
        except Exception:
            continue
        counts[key] += 1
        try:
            size = sys.getsizeof(obj)
        except Exception:
            size = 0
        sizes[key] += size
        bytes_total += size
    top = [_type_row(name, count, sizes[name]) for name, count in counts.most_common(n)]
    watched = [
        _type_row(name, counts[name], sizes[name]) for name in sorted(watch or ())
    ]
    return TypeCensus(top=top, total=total, watch=watched, bytes_total=int(bytes_total))


def _cache_event_count(value: Any, attr: str = "events") -> int:
    """Return ``len(value.attr)`` for a snapshot-cache entry, else 0."""
    try:
        events = getattr(value, attr, None)
        if events is None:
            return 0
        return len(events)
    except Exception:
        return 0


def _locked_mapping_items(cache: Any, lock: Any | None = None) -> list[tuple[Any, Any]]:
    """Copy ``cache`` items while holding *lock* or ``cache._lock``."""
    held = lock if lock is not None else getattr(cache, "_lock", None)
    if held is None:
        try:
            return list(OrderedDict.items(cache))
        except Exception:
            entries = getattr(cache, "_entries", None)
            if isinstance(entries, Mapping):
                return list(entries.items())
            return []
    try:
        held.acquire()
    except Exception:
        return []
    try:
        try:
            return list(OrderedDict.items(cache))
        except Exception:
            entries = getattr(cache, "_entries", None)
            if isinstance(entries, Mapping):
                return list(entries.items())
            return []
    finally:
        try:
            held.release()
        except Exception:
            pass


def _snapshot_cache_census(cache: Any) -> dict[str, Any]:
    """Summarize ``ARTIFACT_SNAPSHOT_CACHE`` generations and retained records."""
    items = _locked_mapping_items(cache)
    generations: list[dict[str, Any]] = []
    record_total = 0
    for key, value in items:
        snapshot = value[1] if isinstance(value, tuple) and len(value) >= 2 else None
        records = _cache_event_count(snapshot, "records")
        record_total += records
        key_parts = (
            [str(part) for part in key] if isinstance(key, tuple) else [str(key)]
        )
        generations.append({"key": key_parts, "records": records})
    return {
        "entries": len(items),
        "max_entries": getattr(cache, "_max_entries", None),
        "record_total": record_total,
        "generations": generations,
    }


def _projected_detail_owner_census(
    owner: Any,
    *,
    lock: Any | None = None,
    max_entries: int | None = None,
) -> dict[str, Any]:
    """Count concrete hydrated Agent generations tracked by the weak owner."""
    items = _locked_mapping_items(owner, lock=lock)
    live_agents = []
    for _generation, reference in items:
        if not callable(reference):
            continue
        agent = reference()
        if agent is not None:
            live_agents.append(agent)
    return {
        "entries": len(items),
        "max_entries": max_entries,
        "live_rows": len(live_agents),
        "hydrated_rows": sum(
            getattr(agent, "record_shape", None) == "full" for agent in live_agents
        ),
        "stale_references": len(items) - len(live_agents),
    }


def _lru_cache_census(cache: Any, *, event_attr: str = "events") -> dict[str, Any]:
    """Summarize a ``BoundedLRUCache`` of snapshot entries."""
    items = _locked_mapping_items(cache)
    event_total = 0
    per_key: list[dict[str, Any]] = []
    for key, value in items:
        count = _cache_event_count(value, event_attr)
        event_total += count
        per_key.append({"key": str(key), "events": count})
    return {
        "entries": len(items),
        "max_entries": getattr(cache, "max_entries", None),
        "event_total": event_total,
        "keys": per_key,
    }


def _index_file_cache_census(
    cache: Any,
    lock: Any | None = None,
    *,
    max_entries: int | None = None,
    max_rows_per_entry: int | None = None,
    max_bytes_per_entry: int | None = None,
) -> dict[str, Any]:
    """Summarize targeted artifact-file association cache row counts."""
    items = _locked_mapping_items(cache, lock=lock)
    row_total = 0
    paths: list[dict[str, Any]] = []
    for key, value in items:
        rows = getattr(value, "rows", None)
        if rows is None and isinstance(value, tuple) and len(value) >= 2:
            rows = value[1]
        try:
            count = len(rows) if rows is not None else 0
        except Exception:
            count = 0
        row_total += count
        if isinstance(key, tuple) and key:
            path = str(key[0])
        else:
            path = str(key)
        paths.append({"path": path, "rows": count})
    return {
        "entries": len(items),
        "max_entries": max_entries,
        "max_rows_per_entry": max_rows_per_entry,
        "max_bytes_per_entry": max_bytes_per_entry,
        "row_total": row_total,
        "paths": paths,
    }


def _stranded_report_cache_census(cache: Any) -> dict[str, Any]:
    """Count the bounded report graphs retained for each project."""
    items = _locked_mapping_items(cache)
    candidate_total = 0
    title_total = 0
    verdict_index_total = 0
    stranded_id_total = 0
    blocked_id_total = 0
    for _key, entry in items:
        snapshot = getattr(entry, "snapshot", None)
        report = getattr(snapshot, "report", None)
        candidate_total += _cache_event_count(report, "verdicts")
        title_total += _cache_event_count(snapshot, "titles")
        verdict_index_total += _cache_event_count(entry, "verdict_index")
        stranded_id_total += _cache_event_count(report, "stranded_ids")
        blocked_id_total += _cache_event_count(report, "blocked_ids")
    return {
        "entries": len(items),
        "max_entries": getattr(cache, "_max_entries", None),
        "candidate_verdict_total": candidate_total,
        "title_total": title_total,
        "verdict_index_total": verdict_index_total,
        "stranded_id_total": stranded_id_total,
        "blocked_id_total": blocked_id_total,
    }


def known_cache_census() -> list[dict[str, Any]]:
    """Probe already-imported module-level caches; never import new modules."""
    probes: tuple[tuple[str, str, str, str], ...] = (
        (
            "sase.ace.tui.models._agent_loader_artifact_cache",
            "ARTIFACT_SNAPSHOT_CACHE",
            "src/sase/ace/tui/models/_agent_loader_artifact_cache.py",
            "snapshot",
        ),
        (
            "sase.ace.tui.models._projected_record_detail",
            "_detail_owner",
            "src/sase/ace/tui/models/_projected_record_detail.py",
            "projected_detail",
        ),
        (
            "sase.core.artifact_file_explicit",
            "_artifact_file_association_cache",
            "src/sase/core/artifact_file_explicit.py",
            "index",
        ),
        (
            "sase.ace.tui.artifact_reads",
            "_artifact_reads_cache",
            "src/sase/ace/tui/artifact_reads.py",
            "lru",
        ),
        (
            "sase.ace.tui.artifact_reads",
            "_artifact_reads_context_cache",
            "src/sase/ace/tui/artifact_reads.py",
            "lru",
        ),
        (
            "sase.ace.tui.memory_reads",
            "_memory_reads_cache",
            "src/sase/ace/tui/memory_reads.py",
            "lru",
        ),
        (
            "sase.ace.tui.memory_reads",
            "_memory_reads_context_cache",
            "src/sase/ace/tui/memory_reads.py",
            "lru",
        ),
        (
            "sase.ace.tui._bead_touches_loader",
            "_bead_touches_cache",
            "src/sase/ace/tui/_bead_touches_loader.py",
            "lru",
        ),
        (
            "sase.ace.tui._bead_touches_loader",
            "_bead_touches_context_cache",
            "src/sase/ace/tui/_bead_touches_loader.py",
            "lru",
        ),
        (
            "sase.ace.tui.models.agent_stranded",
            "_STRANDED_REPORT_CACHE",
            "src/sase/ace/tui/models/agent_stranded.py",
            "stranded",
        ),
        (
            "sase.ace.tui.glossary_reads",
            "_glossary_reads_snapshot_cache",
            "src/sase/ace/tui/glossary_reads.py",
            "lru",
        ),
    )
    rows: list[dict[str, Any]] = []
    for module_name, attr, anchor, kind in probes:
        try:
            module = sys.modules.get(module_name)
            if module is None:
                rows.append(
                    {
                        "name": f"{module_name}.{attr}",
                        "anchor": anchor,
                        "imported": False,
                        "status": "module_not_imported",
                    }
                )
                continue
            cache = getattr(module, attr, None)
            if cache is None:
                rows.append(
                    {
                        "name": f"{module_name}.{attr}",
                        "anchor": anchor,
                        "imported": True,
                        "present": False,
                        "status": "missing_expected_owner",
                    }
                )
                continue
            if kind == "snapshot":
                extra = _snapshot_cache_census(cache)
            elif kind == "projected_detail":
                extra = _projected_detail_owner_census(
                    cache,
                    lock=getattr(module, "_detail_owner_lock", None),
                    max_entries=getattr(module, "_DETAIL_OWNER_BOUND", None),
                )
            elif kind == "index":
                extra = _index_file_cache_census(
                    cache,
                    lock=getattr(module, "_artifact_file_association_cache_lock", None),
                    max_entries=getattr(module, "_ASSOCIATION_CACHE_MAX_ENTRIES", None),
                    max_rows_per_entry=getattr(
                        module, "_ASSOCIATION_CACHE_MAX_ROWS", None
                    ),
                    max_bytes_per_entry=getattr(
                        module, "_ASSOCIATION_CACHE_MAX_BYTES", None
                    ),
                )
            elif kind == "stranded":
                extra = _stranded_report_cache_census(cache)
            else:
                extra = _lru_cache_census(cache)
                row_limit = getattr(
                    module,
                    "MAX_KEPT_READS",
                    getattr(module, "MAX_KEPT_TOUCHES", None),
                )
                if isinstance(row_limit, int) and row_limit > 0:
                    extra["max_rows_per_entry"] = row_limit
                    extra["max_retained_rows"] = (
                        extra["max_entries"] * row_limit
                        if isinstance(extra["max_entries"], int)
                        else None
                    )
            rows.append(
                {
                    "name": f"{module_name}.{attr}",
                    "anchor": anchor,
                    "imported": True,
                    "present": True,
                    "status": "present",
                    **extra,
                }
            )
        except Exception:
            rows.append(
                {
                    "name": f"{module_name}.{attr}",
                    "anchor": anchor,
                    "error": True,
                }
            )
    return rows
