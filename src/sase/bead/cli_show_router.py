"""Store routing for ``sase bead show``."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead.store_locator import open_bead_project_for_beads_dir

if TYPE_CHECKING:
    from sase.bead.cross_project import BeadStoreOrigin


class ShowStoreRoutingError(ValueError):
    """A show request could not be routed to a readable bead store."""


@dataclass(frozen=True)
class RoutedShowStore:
    """One bead store selected for a show lookup."""

    view: Any
    origin: BeadStoreOrigin | None


class ShowStoreRouter:
    """Reuse local and foreign bead stores across one ``show`` invocation."""

    def __init__(self, local_view: Any, *, project_ref: str | None = None) -> None:
        self.local_view = local_view
        self.project_ref = project_ref
        self._stack = ExitStack()
        self._projects: dict[Path, Any] = {}
        self._pinned: RoutedShowStore | None = None

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
            return RoutedShowStore(self.local_view, None)
        if self._pinned is None:
            self._pinned = self._resolve_pinned_store()
        return self._pinned

    def foreign_store_for_bead_id(self, bead_id: str) -> RoutedShowStore | None:
        """Return the foreign store named by *bead_id*'s prefix, if any."""
        if self.project_ref is not None:
            return None

        from sase.bead.cross_project import (
            AmbiguousBeadProjectError,
            origin_for_bead_id,
        )

        try:
            origin = origin_for_bead_id(bead_id)
        except AmbiguousBeadProjectError as exc:
            raise ShowStoreRoutingError(str(exc)) from exc
        if origin is None:
            return None
        return self._store_for_origin(origin, requested_id=bead_id)

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
