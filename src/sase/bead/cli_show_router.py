"""Store routing for ``sase bead show``."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead.store_locator import open_bead_project_for_beads_dir
from sase.core.bead_target_routing_facade import BeadTargetRoute

if TYPE_CHECKING:
    from sase.bead.cross_project import BeadStoreOrigin, BeadStoreSnapshot


class ShowStoreRoutingError(ValueError):
    """A show request could not be routed to a readable bead store."""


@dataclass(frozen=True)
class RoutedShowStore:
    """One bead store selected for a show lookup."""

    view: Any
    origin: BeadStoreOrigin | None


@dataclass(frozen=True)
class _RoutedShowTarget:
    """One show target resolved to a store and canonical bead ID."""

    requested_id: str
    resolved_id: str
    store: RoutedShowStore


class ShowStoreRouter:
    """Reuse local and foreign bead stores across one ``show`` invocation."""

    def __init__(
        self,
        local_view: Any | None,
        *,
        project_ref: str | None = None,
    ) -> None:
        self.local_view = local_view
        self.project_ref = project_ref
        self._stack = ExitStack()
        self._projects: dict[Path, Any] = {}
        self._pinned: RoutedShowStore | None = None
        self._snapshots: tuple[BeadStoreSnapshot, ...] | None = None

    def __enter__(self) -> ShowStoreRouter:
        return self

    def __exit__(self, *exc_info: object) -> None:
        del exc_info
        self._stack.close()

    @property
    def is_project_pinned(self) -> bool:
        """Return whether ``-P/--project`` selected one store for all IDs."""
        return self.project_ref is not None

    def primary_store(self) -> RoutedShowStore:
        """Return the store that should be consulted before prefix routing."""
        if self.project_ref is None:
            if self.local_view is None:
                raise ShowStoreRoutingError("no local bead store is available")
            return RoutedShowStore(self.local_view, None)
        if self._pinned is None:
            self._pinned = self._resolve_pinned_store()
        return self._pinned

    def foreign_store_for_bead_id(self, bead_id: str) -> RoutedShowStore | None:
        """Return the foreign store named by *bead_id*'s prefix, if any."""
        if self.project_ref is not None:
            return None
        try:
            return self.foreign_target_for_bead_id(bead_id).store
        except KeyError:
            return None

    def route_target(self, bead_id: str) -> _RoutedShowTarget:
        """Resolve *bead_id* through the shared Rust-backed route policy."""
        if self.project_ref is not None:
            return self._route_pinned_target(bead_id)

        if self.local_view is not None:
            return _RoutedShowTarget(
                requested_id=bead_id,
                resolved_id=bead_id,
                store=RoutedShowStore(self.local_view, None),
            )
        if not _looks_like_full_bead_id(bead_id):
            raise ShowStoreRoutingError("no local bead store is available")

        return self.foreign_target_for_bead_id(bead_id)

    def foreign_target_for_bead_id(self, bead_id: str) -> _RoutedShowTarget:
        """Resolve a full bead ID against enabled foreign project snapshots."""
        if self.project_ref is not None:
            raise KeyError(bead_id)
        if not _looks_like_full_bead_id(bead_id):
            raise KeyError(bead_id)

        route = self._route_with_enabled_projects(bead_id)
        if route is None:
            raise KeyError(bead_id)
        if route.error is not None:
            if route.error.kind == "not_found":
                raise KeyError(bead_id)
            raise ShowStoreRoutingError(route.error.message)
        if route.resolved_id is None or route.store is None:
            raise KeyError(bead_id)
        snapshot = self._snapshot_for_store_key(route.store.store_key)
        if snapshot is None:
            raise KeyError(bead_id)
        return _RoutedShowTarget(
            requested_id=bead_id,
            resolved_id=route.resolved_id,
            store=self._store_for_origin(snapshot.origin, requested_id=bead_id),
        )

    def _resolve_pinned_store(self) -> RoutedShowStore:
        from sase.bead.cross_project import (
            AmbiguousBeadProjectError,
            origin_for_project_ref,
        )

        assert self.project_ref is not None
        try:
            origin = origin_for_project_ref(self.project_ref)
        except AmbiguousBeadProjectError as exc:
            raise ShowStoreRoutingError(str(exc)) from exc
        if origin is None:
            raise ShowStoreRoutingError(f"project {self.project_ref!r} was not found")
        return self._store_for_origin(origin, requested_id=None)

    def _route_pinned_target(self, bead_id: str) -> _RoutedShowTarget:
        # The pinned store owns every target by definition: carry the raw ID
        # forward and let the show itself resolve it in its single read.
        store = self.primary_store()
        return _RoutedShowTarget(
            requested_id=bead_id,
            resolved_id=bead_id,
            store=store,
        )

    def _route_with_enabled_projects(
        self,
        bead_id: str,
    ) -> BeadTargetRoute | None:
        from sase.bead.cross_project import route_full_id_with_snapshots

        return route_full_id_with_snapshots(
            bead_id,
            self._enabled_snapshots(),
        )

    def _enabled_snapshots(self) -> tuple[BeadStoreSnapshot, ...]:
        if self._snapshots is None:
            from sase.bead.cross_project import enabled_project_store_snapshots

            self._snapshots = enabled_project_store_snapshots()
        return self._snapshots

    def _snapshot_for_store_key(
        self,
        store_key: str,
    ) -> BeadStoreSnapshot | None:
        for snapshot in self._enabled_snapshots():
            if snapshot.store_key == store_key:
                return snapshot
        return None

    def _store_for_origin(
        self,
        origin: BeadStoreOrigin,
        *,
        requested_id: str | None,
    ) -> RoutedShowStore:
        beads_dir = origin.beads_dir
        if beads_dir is None:
            target = f" owns {requested_id!r}," if requested_id is not None else ""
            raise ShowStoreRoutingError(
                f"project {origin.project_label!r}{target} but its bead store is "
                "not materialized on this machine"
            )

        key = beads_dir.expanduser().resolve(strict=False)
        if key not in self._projects:
            try:
                self._projects[key] = self._stack.enter_context(
                    open_bead_project_for_beads_dir(beads_dir)
                )
            except (OSError, RuntimeError, ValueError) as exc:
                raise ShowStoreRoutingError(
                    f"project {origin.project_label!r} bead store is not readable "
                    f"on this machine: {exc}"
                ) from exc
        return RoutedShowStore(self._projects[key], origin)


__all__ = [
    "RoutedShowStore",
    "ShowStoreRouter",
    "ShowStoreRoutingError",
]


def _looks_like_full_bead_id(bead_id: str) -> bool:
    from sase.bead.cross_project import bead_id_prefix

    return bead_id_prefix(bead_id) is not None
