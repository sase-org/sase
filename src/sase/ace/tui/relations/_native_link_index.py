"""Shared single-flight native artifact-link index handles.

One compilation per aggregate generation for concurrent consumers:
:class:`~.artifact_links.ArtifactLinksSnapshot` rows are converted in a
single bulk pass into an immutable ``sase_core`` index, and the opaque
handle is memoized by snapshot signature within project scope. Both the
link-chip index (:mod:`.link_index`) and the pane projection
(:func:`.artifact_links.artifact_link_edges`) resolve through this module
so they share one handle per generation.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Event, RLock
import time
from typing import Any

from sase.ace.tui.util.trace import tui_trace
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.artifact_link_index_facade import build_index, index_stats

_HANDLE_CACHE_MAX = 8
_SYNTHETIC_CACHE_MAX = 64


class _CachedHandle:
    __slots__ = ("source_key", "identity_fp", "relations_fp", "handle", "seq")

    def __init__(
        self,
        source_key: tuple[object, ...],
        identity_fp: tuple[object, ...],
        relations_fp: tuple[object, ...],
        handle: Any,
        seq: int,
    ) -> None:
        self.source_key = source_key
        self.identity_fp = identity_fp
        self.relations_fp = relations_fp
        self.handle = handle
        self.seq = seq

    def matches(
        self,
        source_key: tuple[object, ...],
        identity_fp: tuple[object, ...],
        relations_fp: tuple[object, ...],
    ) -> bool:
        return (
            self.source_key == source_key
            and self.identity_fp == identity_fp
            and self.relations_fp == relations_fp
        )


class _Inflight:
    __slots__ = ("event", "handle", "error", "snapshot")

    def __init__(self, snapshot: Any) -> None:
        self.event = Event()
        self.handle: Any = None
        self.error: BaseException | None = None
        # Pin the snapshot while building so a synthetic id() key cannot be
        # recycled by an unrelated object mid-build.
        self.snapshot = snapshot


_REGISTRY_LOCK = RLock()
_HANDLE_CACHE: OrderedDict[tuple[object, ...], _CachedHandle] = OrderedDict()
_SYNTHETIC_CACHE: OrderedDict[tuple[object, ...], _CachedHandle] = OrderedDict()
_SYNTHETIC_REFS: dict[tuple[object, ...], Any] = {}
_INFLIGHT: dict[tuple[object, ...], _Inflight] = {}
_SEQ = 0


def _next_seq() -> int:
    global _SEQ
    _SEQ += 1
    return _SEQ


def _scope_for_source_key(source_key: tuple[object, ...]) -> tuple[object, ...]:
    """Derive the cache scope from a snapshot's ``source_key``.

    Artifact-link snapshots carry ``((project_key, mtime_ns, size), ...)``;
    the scope is the project-key tuple. The empty snapshot's ``()`` key maps
    to the ``()`` scope. An unexpected shape falls back to the full key so a
    mismatched entry can never be served.
    """

    if not source_key:
        return ()
    scope: list[object] = []
    for entry in source_key:
        if (
            isinstance(entry, (tuple, list))
            and len(entry) >= 1
            and isinstance(entry[0], str)
        ):
            scope.append(entry[0])
        else:
            return tuple(source_key)
    return tuple(scope)


def _is_synthetic_snapshot(snapshot: Any) -> bool:
    """Return whether *snapshot* must bypass global signature reuse.

    Synthetic or empty-signature snapshots with actual rows (tests and
    in-memory fixtures) share placeholder keys, so two distinct snapshots
    must never collide on one cached handle.
    """

    if not snapshot.rows:
        return False
    if not snapshot.source_key:
        return True
    return _scope_for_source_key(tuple(snapshot.source_key)) == tuple(
        snapshot.source_key
    )


def _identity_fingerprint(identity: AgentIdentitySnapshot) -> tuple[object, ...]:
    owner = identity.owner
    return (
        None if owner is None else owner.username,
        None if owner is None else owner.machine_name,
        tuple(identity.sibling_machines),
        tuple(identity.known_owner_roots),
    )


def _relations_fingerprint(
    relations: Any,
) -> tuple[object, ...]:
    try:
        items = list(relations)
    except TypeError:
        return ()
    fingerprint = []
    for item in items:
        try:
            fingerprint.append(
                (
                    str(item.get("slug") or ""),
                    str(item.get("inverse") or ""),
                    bool(item.get("directed", True)),
                )
            )
        except AttributeError:
            continue
    return tuple(sorted(fingerprint))


def _assembled_relations() -> list[dict[str, Any]]:
    from sase.sdd._artifact_link_store_support import assembled_artifact_relations

    return [
        {
            "slug": str(item.get("slug") or ""),
            "inverse": str(item.get("inverse") or ""),
            "directed": bool(item.get("directed", True)),
        }
        for item in assembled_artifact_relations()
    ]


def native_handle_for_snapshot(snapshot: Any) -> Any:
    """Return the shared native handle for *snapshot*, compiling once.

    Two callers for the same snapshot wait on one compilation instead of
    building twice. A failed build releases all waiters and allows retry.
    """

    identity = AgentIdentitySnapshot.current()
    relations = _assembled_relations()
    identity_fp = _identity_fingerprint(identity)
    relations_fp = _relations_fingerprint(relations)
    if _is_synthetic_snapshot(snapshot):
        key: tuple[object, ...] = (
            "__synthetic__",
            id(snapshot),
            identity_fp,
            relations_fp,
        )
        return _handle_for_key(
            key,
            key,
            snapshot,
            identity,
            relations,
            synthetic=True,
        )
    source_key = tuple(snapshot.source_key)
    scope = _scope_for_source_key(source_key)
    key = (scope, source_key, identity_fp, relations_fp)
    return _handle_for_key(key, scope, snapshot, identity, relations, synthetic=False)


def _handle_for_key(
    key: tuple[object, ...],
    slot: tuple[object, ...],
    snapshot: Any,
    identity: AgentIdentitySnapshot,
    relations: list[dict[str, Any]],
    *,
    synthetic: bool,
) -> Any:
    source_key = tuple(snapshot.source_key)
    identity_fp = _identity_fingerprint(identity)
    relations_fp = _relations_fingerprint(relations)
    with _REGISTRY_LOCK:
        cache = _SYNTHETIC_CACHE if synthetic else _HANDLE_CACHE
        cached = cache.get(slot)
        if cached is not None and cached.matches(source_key, identity_fp, relations_fp):
            cache.move_to_end(slot)
            return cached.handle
        inflight = _INFLIGHT.get(key)
        if inflight is None:
            inflight = _Inflight(snapshot)
            _INFLIGHT[key] = inflight
            owner = True
            seq = _next_seq()
        else:
            owner = False
    if not owner:
        # Wait outside the registry lock so scopes never block each other.
        inflight.event.wait()
        with _REGISTRY_LOCK:
            cache = _SYNTHETIC_CACHE if synthetic else _HANDLE_CACHE
            cached = cache.get(slot)
            if cached is not None and cached.matches(
                source_key, identity_fp, relations_fp
            ):
                cache.move_to_end(slot)
                return cached.handle
            if inflight.error is not None:
                raise inflight.error
            return inflight.handle
    try:
        handle = _compile(snapshot, identity, relations)
    except BaseException as exc:
        with _REGISTRY_LOCK:
            if _INFLIGHT.get(key) is inflight:
                del _INFLIGHT[key]
            inflight.error = exc
            inflight.event.set()
        raise
    with _REGISTRY_LOCK:
        cache = _SYNTHETIC_CACHE if synthetic else _HANDLE_CACHE
        cached = cache.get(slot)
        # A slow older build must not replace a newer published generation.
        if cached is None or seq >= cached.seq:
            cache[slot] = _CachedHandle(
                source_key, identity_fp, relations_fp, handle, seq
            )
            cache.move_to_end(slot)
            if synthetic:
                _SYNTHETIC_REFS[slot] = snapshot
                while len(cache) > _SYNTHETIC_CACHE_MAX:
                    evicted, _ = cache.popitem(last=False)
                    _SYNTHETIC_REFS.pop(evicted, None)
            else:
                while len(cache) > _HANDLE_CACHE_MAX:
                    cache.popitem(last=False)
        if _INFLIGHT.get(key) is inflight:
            del _INFLIGHT[key]
        inflight.handle = handle
        inflight.event.set()
    return handle


def _compile(
    snapshot: Any,
    identity: AgentIdentitySnapshot,
    relations: list[dict[str, Any]],
) -> Any:
    """Convert rows in one bulk pass and compile the immutable index."""

    with tui_trace("links.index_build") as extra:
        started = time.perf_counter()
        handle = build_index(snapshot.rows, identity=identity, relations=relations)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        try:
            stats = index_stats(handle)
        except Exception:  # noqa: BLE001 - stats only annotate the span
            stats = {}
        extra["elapsed_ms"] = elapsed_ms
        for name in (
            "raw_row_count",
            "indexed_row_count",
            "canonical_ref_count",
            "chip_ref_count",
        ):
            if name in stats:
                extra[name] = stats[name]
    return handle


def clear_native_link_index_cache() -> None:
    """Drop cached handles. Tests only; safe with pending builds.

    In-flight compilations still resolve their waiters; their handles are
    published normally afterwards. Eviction never invalidates handles
    already held by callers.
    """

    with _REGISTRY_LOCK:
        _HANDLE_CACHE.clear()
        _SYNTHETIC_CACHE.clear()
        _SYNTHETIC_REFS.clear()


__all__ = [
    "_scope_for_source_key",
    "clear_native_link_index_cache",
    "native_handle_for_snapshot",
]
