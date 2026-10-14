"""An O(1), app-owned index from a link-graph ref to its ordered chips.

The chip graph is compiled once per aggregate generation into an immutable
``sase_core`` index (see :mod:`.artifact_links` snapshots and
:mod:`._native_link_index`); this module adapts one shared native handle
per generation into lazily materialized :class:`LinkChip` records. Chip
records are created only for refs callers actually query -- membership and
ordinary lookups never enumerate the graph.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any

from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_link_index_facade import (
    build_index as _facade_build_index,
)
from sase.core.artifact_link_index_facade import (
    index_chips,
    index_target,
    target_from_wire,
)
from sase.sdd._artifact_link_store_support import (
    assembled_artifact_relations,
    canonicalize_artifact_link_ref,
)

from ._native_link_index import native_handle_for_snapshot
from .artifact_links import ArtifactLinksSnapshot
from .link_subject import accent_and_icon_for_ref


@dataclass(frozen=True, slots=True)
class LinkChip:
    """One typed edge from a subject's perspective, ready to display."""

    relation: str
    label: str
    directed: bool
    this_is_source: bool
    neighbor_ref: str
    neighbor_target: ArtifactEntryTarget | None
    accent: str
    icon: str
    why: str
    origin: str
    uses: int
    created_by: str
    created_at: str
    writable: bool


class _ChipMapping(Mapping[str, tuple[LinkChip, ...]]):
    """Lazy per-ref chip view over one shared native handle.

    Values are converted from native chip wires on first query and kept in
    a bounded per-handle cache; membership never enumerates the graph.
    """

    def __init__(self, handle: Any) -> None:
        self._handle = handle
        self._lock = RLock()
        self._chips: OrderedDict[str, tuple[LinkChip, ...]] = OrderedDict()
        self._styles: dict[tuple[str, str | None], tuple[str, str]] = {}
        self._max = 128

    def __getitem__(self, ref: str) -> tuple[LinkChip, ...]:
        with self._lock:
            cached = self._chips.get(ref)
            if cached is not None:
                self._chips.move_to_end(ref)
                return cached
        chips = tuple(
            _chip_from_wire(wire, self._styles)
            for wire in index_chips(self._handle, _canonicalize(ref))
        )
        with self._lock:
            self._chips[ref] = chips
            self._chips.move_to_end(ref)
            while len(self._chips) > self._max:
                self._chips.popitem(last=False)
        return chips

    def __contains__(self, ref: object) -> bool:
        if not isinstance(ref, str):
            return False
        with self._lock:
            # A cached empty tuple records an absent ref, not membership.
            if self._chips.get(ref):
                return True
        try:
            return bool(
                index_target(self._handle, _canonicalize(ref)).get("present", False)
            )
        except Exception:  # noqa: BLE001 - membership degrades to absent
            return False

    def __iter__(self) -> Iterator[str]:
        raise TypeError(
            "LinkIndex.by_ref is a lazy per-ref view; use chips_for(ref) "
            "instead of enumerating the graph"
        )

    def __len__(self) -> int:
        raise TypeError(
            "LinkIndex.by_ref is a lazy per-ref view; use chips_for(ref) "
            "instead of enumerating the graph"
        )


class _TargetsMapping(Mapping[str, ArtifactEntryTarget | None]):
    """Lazy per-ref target view over one shared native handle.

    Entries whose target is ``None`` are still members: an indexed
    non-selectable ref (bug/chat/chop) is present with no destination,
    which :func:`LinkIndex.target_for` reports as ``None`` while ``in``
    stays true.
    """

    def __init__(self, handle: Any) -> None:
        self._handle = handle

    def __getitem__(self, ref: str) -> ArtifactEntryTarget | None:
        try:
            payload = index_target(self._handle, _canonicalize(ref))
        except Exception as exc:  # noqa: BLE001 - missing refs KeyError
            raise KeyError(ref) from exc
        if not payload.get("present", False):
            raise KeyError(ref)
        return target_from_wire(payload.get("target"))

    def __contains__(self, ref: object) -> bool:
        if not isinstance(ref, str):
            return False
        try:
            return bool(
                index_target(self._handle, _canonicalize(ref)).get("present", False)
            )
        except Exception:  # noqa: BLE001 - membership degrades to absent
            return False

    def __iter__(self) -> Iterator[str]:
        raise TypeError(
            "LinkIndex.targets_by_ref is a lazy per-ref view; use "
            "target_for(ref) instead of enumerating the graph"
        )

    def __len__(self) -> int:
        raise TypeError(
            "LinkIndex.targets_by_ref is a lazy per-ref view; use "
            "target_for(ref) instead of enumerating the graph"
        )


@dataclass(frozen=True, slots=True)
class LinkIndex:
    """App-owned O(1) index from a canonical ref to its ordered chips."""

    by_ref: Mapping[str, tuple[LinkChip, ...]]
    targets_by_ref: Mapping[str, ArtifactEntryTarget | None]
    source_key: tuple[object, ...]

    def chips_for(self, ref: str) -> tuple[LinkChip, ...]:
        """Return *ref*'s ordered chips, or an empty tuple when it has none."""

        return self.by_ref.get(ref, ())

    def target_for(self, ref: str) -> ArtifactEntryTarget | None:
        """Return *ref*'s indexed destination target, when the graph knows one."""

        return self.targets_by_ref.get(ref)


def link_index_for_snapshot(snapshot: ArtifactLinksSnapshot) -> LinkIndex:
    """Return the cached :class:`LinkIndex` for *snapshot*.

    Gated by the snapshot's own ``source_key`` within its project scope --
    the same mtime+size aggregate signature
    :func:`.artifact_links.load_artifact_links_snapshot` already uses -- so a
    caller on the render path pays the build cost at most once per aggregate
    change, and a superseded signature replaces its scope's entry. Two
    callers for the same snapshot compile once through the shared native
    handle; synthetic snapshots with placeholder keys stay separate.
    """

    return _index_for_handle(native_handle_for_snapshot(snapshot), snapshot)


def _index_for_handle(handle: Any, snapshot: ArtifactLinksSnapshot) -> LinkIndex:
    return LinkIndex(
        by_ref=_ChipMapping(handle),
        targets_by_ref=_TargetsMapping(handle),
        source_key=tuple(snapshot.source_key),
    )


def _build_link_index(snapshot: ArtifactLinksSnapshot) -> LinkIndex:
    """Build a fresh :class:`LinkIndex` from *snapshot*'s rows.

    Uncached companion to :func:`link_index_for_snapshot` for tests and
    measurement helpers; production callers share the cached handle.
    """

    handle = _facade_build_index(
        [dict(row) for row in snapshot.rows],
        identity=AgentIdentitySnapshot.current(),
        relations=[
            {
                "slug": str(item.get("slug") or ""),
                "inverse": str(item.get("inverse") or ""),
                "directed": bool(item.get("directed", True)),
            }
            for item in assembled_artifact_relations()
        ],
    )
    return _index_for_handle(handle, snapshot)


def _chip_from_wire(
    wire: Mapping[str, Any],
    style_cache: dict[tuple[str, str | None], tuple[str, str]],
) -> LinkChip:
    neighbor_target = target_from_wire(wire.get("neighbor_target"))
    neighbor_kind = str(wire.get("neighbor_kind") or "")
    style_key = (
        neighbor_kind,
        None if neighbor_target is None else neighbor_target.pane_id,
    )
    accent_icon = style_cache.get(style_key)
    if accent_icon is None:
        accent_icon = accent_and_icon_for_ref(neighbor_kind, neighbor_target)
        style_cache[style_key] = accent_icon
    accent, icon = accent_icon
    return LinkChip(
        relation=str(wire.get("relation") or ""),
        label=str(wire.get("label") or ""),
        directed=bool(wire.get("directed", True)),
        this_is_source=bool(wire.get("this_is_source", True)),
        neighbor_ref=str(wire.get("neighbor_ref") or ""),
        neighbor_target=neighbor_target,
        accent=accent,
        icon=icon,
        why=str(wire.get("why") or ""),
        origin=str(wire.get("origin") or ""),
        uses=_uses_value(wire.get("uses")),
        created_by=str(wire.get("created_by") or ""),
        created_at=str(wire.get("created_at") or ""),
        writable=bool(wire.get("writable", True)),
    )


def _uses_value(value: Any) -> int:
    try:
        uses = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, uses)


def _canonicalize(ref: str) -> str:
    try:
        return str(canonicalize_artifact_link_ref(ref))
    except Exception:  # noqa: BLE001 - a malformed ref degrades to itself
        return ref


__all__ = [
    "LinkChip",
    "LinkIndex",
    "_build_link_index",
    "link_index_for_snapshot",
]
