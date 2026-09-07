"""Public batch-reservation facade for the durable agent-name registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.agent.names._registry_batch import (
        RegisteredNameReservation,
        RegisteredNameReservationBatchResult,
        RegisteredNameReservationSnapshot,
    )

_ReservationBatchHooksFactory = Callable[[], Any]


class _RegistryBatchFacade:
    def __init__(
        self,
        reservation_batch_hooks: _ReservationBatchHooksFactory,
    ) -> None:
        self._reservation_batch_hooks = reservation_batch_hooks

    def reserve_registered_names(
        self,
        reservations: Sequence[tuple[str, str | Path]],
    ) -> RegisteredNameReservationBatchResult:
        """Reserve multiple planned names through one fresh registry transaction."""
        from sase.agent.names._registry_batch import reserve_registered_names as _impl

        return _impl(self._reservation_batch_hooks(), reservations)

    def claim_registered_names(
        self,
        reservations: Sequence[tuple[str, str | Path]],
        *,
        replace_existing: bool = False,
    ) -> RegisteredNameReservationBatchResult:
        """Claim multiple names through one fresh registry transaction."""
        from sase.agent.names._registry_batch import claim_registered_names as _impl

        return _impl(
            self._reservation_batch_hooks(),
            reservations,
            replace_existing=replace_existing,
        )

    def mutate_registered_name_reservations(
        self,
        reservations: Sequence[RegisteredNameReservation | Mapping[str, Any]],
        *,
        max_retries: int = 3,
    ) -> RegisteredNameReservationBatchResult:
        """Apply a core-planned reservation batch to the registry."""
        from sase.agent.names._registry_batch import (
            mutate_registered_name_reservations as _impl,
        )

        return _impl(
            self._reservation_batch_hooks(),
            reservations,
            max_retries=max_retries,
        )

    def registered_name_reservation_snapshot(
        self,
    ) -> RegisteredNameReservationSnapshot:
        """Return one fresh registry snapshot for in-memory lookups."""
        from sase.agent.names._registry_batch import (
            registered_name_reservation_snapshot as _impl,
        )

        return _impl(self._reservation_batch_hooks())

    def planned_registered_name_belongs_to_artifact(
        self,
        name: str,
        artifact_dir: str | Path,
    ) -> bool:
        """Return whether a raw planned reservation belongs to *artifact_dir*."""
        from sase.agent.names._registry_batch import (
            planned_registered_name_belongs_to_artifact as _impl,
        )

        return _impl(self._reservation_batch_hooks(), name, artifact_dir)

    def claim_exact_planned_registered_name(
        self,
        name: str,
        artifact_dir: str | Path,
    ) -> bool:
        """Convert a matching planned reservation without archive discovery."""
        from sase.agent.names._registry_batch import (
            claim_exact_planned_registered_name as _impl,
        )

        return _impl(self._reservation_batch_hooks(), name, artifact_dir)


def bind_registry_batch(
    reservation_batch_hooks: _ReservationBatchHooksFactory,
) -> _RegistryBatchFacade:
    """Bind registry batch functions to runtime hooks."""
    return _RegistryBatchFacade(reservation_batch_hooks)
