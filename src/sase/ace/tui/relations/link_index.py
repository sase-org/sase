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
from dataclasses import dataclass, field as dataclass_field
from threading import Event, RLock
from typing import TYPE_CHECKING
from typing import Any

from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.sdd._artifact_link_store_support import (
    assembled_artifact_relations,
    canonicalize_artifact_link_ref,
)

if TYPE_CHECKING:
    from .artifact_links import ArtifactLinksSnapshot


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

    def __init__(
        self, handle: Any, style_context: tuple[tuple[str, str, str], ...]
    ) -> None:
        self._handle = handle
        self._lock = RLock()
        self._chips: OrderedDict[str, tuple[LinkChip, ...]] = OrderedDict()
        self._inflight: dict[str, _ChipRequest] = {}
        self._style_context = style_context
        self._styles = {key: (accent, icon) for key, accent, icon in style_context}
        self._max = 128

    def __getitem__(self, ref: str) -> tuple[LinkChip, ...]:
        with self._lock:
            if ref in self._chips:
                self._chips.move_to_end(ref)
                return self._chips[ref]
            request = self._inflight.get(ref)
            owner = request is None
            if request is None:
                request = _ChipRequest()
                self._inflight[ref] = request
        if not owner:
            request.event.wait()
            if request.error is not None:
                raise request.error
            assert request.chips is not None
            return request.chips
        try:
            from sase.core.artifact_link_index_facade import index_chips

            chips = tuple(
                _chip_from_wire(wire, self._styles)
                for wire in index_chips(self._handle, _canonicalize(ref))
            )
        except BaseException as exc:
            with self._lock:
                request.error = exc
                self._inflight.pop(ref, None)
                request.event.set()
            raise
        with self._lock:
            self._chips[ref] = chips
            self._chips.move_to_end(ref)
            while len(self._chips) > self._max:
                self._chips.popitem(last=False)
            request.chips = chips
            self._inflight.pop(ref, None)
            request.event.set()
        return chips

    def cached(self, ref: str) -> tuple[LinkChip, ...] | None:
        """Peek at requested chips without querying the native handle."""
        with self._lock:
            if ref not in self._chips:
                return None
            self._chips.move_to_end(ref)
            return self._chips[ref]

    def __contains__(self, ref: object) -> bool:
        if not isinstance(ref, str):
            return False
        with self._lock:
            # A cached empty tuple records an absent ref, not membership.
            if self._chips.get(ref):
                return True
        try:
            from sase.core.artifact_link_index_facade import index_target

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
            from sase.core.artifact_link_index_facade import (
                index_target,
                target_from_wire,
            )

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
            from sase.core.artifact_link_index_facade import index_target

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

    def cached_chips_for(self, ref: str) -> tuple[LinkChip, ...] | None:
        """Return requested chips if already materialized, without waiting."""
        cached = getattr(self.by_ref, "cached", None)
        if callable(cached):
            return cached(ref)
        # Small in-memory indexes used by callers/tests are already cached.
        return self.by_ref.get(ref, ())


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

    from ._native_link_index import native_handle_for_snapshot

    handle = native_handle_for_snapshot(snapshot)
    return _index_for_handle(handle, snapshot, _capture_style_context())


@dataclass
class _ChipRequest:
    event: Event = dataclass_field(default_factory=Event)
    chips: tuple[LinkChip, ...] | None = None
    error: BaseException | None = None


_VIEW_CACHE_LOCK = RLock()
_VIEW_CACHE: OrderedDict[tuple[object, ...], tuple[Any, LinkIndex]] = OrderedDict()
_VIEW_CACHE_MAX = 8


def _capture_style_context() -> tuple[tuple[str, str, str], ...]:
    """Resolve provider-backed styles on the worker before lazy chip queries."""
    from .._artifact_tab_model import (
        ARTIFACTS_ACCENTS,
        ARTIFACTS_ICONS,
        EXTERNAL_ACCENT,
    )
    from ..artifact_tabs import resolve_artifacts_subtabs
    from .link_subject import _CHOP_ACCENT, _CHOP_ICON, _DEFAULT_ICON, _PLAN_REF_ICON

    styles: dict[str, tuple[str, str]] = {
        "chop": (_CHOP_ACCENT, _CHOP_ICON),
        "job": (_CHOP_ACCENT, _CHOP_ICON),
        "plan": (ARTIFACTS_ACCENTS["ref:plan"], "✎"),
    }
    for pane_id, accent in ARTIFACTS_ACCENTS.items():
        icon = ARTIFACTS_ICONS.get(pane_id, _DEFAULT_ICON)
        styles[pane_id] = (accent, icon)
    for descriptor in resolve_artifacts_subtabs():
        styles[descriptor.id] = (descriptor.accent, descriptor.icon)
    # `plan` has a fixed presentation even though its selectable target is
    # the document-provider pane `ref:plan`.
    styles["ref:plan"] = (ARTIFACTS_ACCENTS["ref:plan"], _PLAN_REF_ICON)
    styles["__external__"] = (EXTERNAL_ACCENT, _DEFAULT_ICON)
    return tuple((key, accent, icon) for key, (accent, icon) in sorted(styles.items()))


def _index_for_handle(
    handle: Any,
    snapshot: ArtifactLinksSnapshot,
    style_context: tuple[tuple[str, str, str], ...],
) -> LinkIndex:
    key = (id(handle), tuple(snapshot.source_key), style_context)
    with _VIEW_CACHE_LOCK:
        cached = _VIEW_CACHE.get(key)
        if cached is not None and cached[0] is handle:
            _VIEW_CACHE.move_to_end(key)
            return cached[1]
        index = LinkIndex(
            by_ref=_ChipMapping(handle, style_context),
            targets_by_ref=_TargetsMapping(handle),
            source_key=tuple(snapshot.source_key),
        )
        _VIEW_CACHE[key] = (handle, index)
        _VIEW_CACHE.move_to_end(key)
        while len(_VIEW_CACHE) > _VIEW_CACHE_MAX:
            _VIEW_CACHE.popitem(last=False)
        return index


def _build_link_index(snapshot: ArtifactLinksSnapshot) -> LinkIndex:
    """Build a fresh :class:`LinkIndex` from *snapshot*'s rows.

    Uncached companion to :func:`link_index_for_snapshot` for tests and
    measurement helpers; production callers share the cached handle.
    """

    from sase.core.artifact_link_index_facade import build_index

    handle = build_index(
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
    return _index_for_handle(handle, snapshot, _capture_style_context())


def _chip_from_wire(
    wire: Mapping[str, Any],
    styles: Mapping[str, tuple[str, str]],
) -> LinkChip:
    from sase.core.artifact_link_index_facade import target_from_wire

    neighbor_target = target_from_wire(wire.get("neighbor_target"))
    neighbor_kind = str(wire.get("neighbor_kind") or "")
    style_key = (
        neighbor_target.pane_id if neighbor_target is not None else neighbor_kind
    )
    accent_icon = styles.get(style_key, styles["__external__"])
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
