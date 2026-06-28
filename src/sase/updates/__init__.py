"""Shared update-status helpers for SASE core and plugins."""

from .cache import (
    get_cached_update_status,
    read_update_status_snapshot,
    revalidate_update_status,
    update_status_snapshot_is_fresh,
    write_update_status_snapshot,
)
from .status import (
    OutdatedComponent,
    UpdateStatus,
    compute_update_status,
)

__all__ = [
    "OutdatedComponent",
    "UpdateStatus",
    "compute_update_status",
    "get_cached_update_status",
    "read_update_status_snapshot",
    "revalidate_update_status",
    "update_status_snapshot_is_fresh",
    "write_update_status_snapshot",
]
