"""Types shared by the publication transaction implementation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sase.agents_sync.inventory import ProjectHoodInventory


REPOSITORY_FAILURE_SCOPE = "repository"


@dataclass(frozen=True, slots=True)
class DrainResult:
    drained: int = 0
    item_errors: tuple[str, ...] = ()
    error: str | None = None
    error_keys: tuple[tuple[str, str], ...] = ()
    failure_scope: str | None = None
    failure_stage: str | None = None


@dataclass(frozen=True, slots=True)
class PublicationTransactionHooks:
    """Facade-owned operations used by the extracted transaction engine."""

    build_inventory: Callable[..., ProjectHoodInventory]
    publish_hood: Callable[..., object]
    update_publications: Callable[..., object]
    acknowledge_publications: Callable[..., object]
    configured_max_attempts: Callable[[], int]
