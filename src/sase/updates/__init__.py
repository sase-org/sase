"""Shared update-status helpers for SASE core and plugins."""

from .cache import (
    DEFAULT_UPDATE_STATUS_TTL_SECONDS,
    SCHEMA_VERSION,
    get_cached_update_status,
    read_update_status_snapshot,
    revalidate_update_status,
    update_status_snapshot_is_fresh,
    write_update_status_snapshot,
)
from .incoming_commits import (
    CommitSourceSpec,
    CommitSummary,
    IncomingCommits,
    IncomingCommitsCacheKey,
    allocate_commit_budget,
    component_commit_spec,
    core_package_commit_spec,
    fetch_incoming_commits,
    plugin_entry_commit_spec,
)
from .status import (
    OutdatedComponent,
    UpdateStatus,
    build_update_status,
    compute_update_status,
)

__all__ = [
    "CommitSourceSpec",
    "CommitSummary",
    "DEFAULT_UPDATE_STATUS_TTL_SECONDS",
    "IncomingCommits",
    "IncomingCommitsCacheKey",
    "OutdatedComponent",
    "SCHEMA_VERSION",
    "UpdateStatus",
    "allocate_commit_budget",
    "build_update_status",
    "component_commit_spec",
    "compute_update_status",
    "core_package_commit_spec",
    "fetch_incoming_commits",
    "get_cached_update_status",
    "plugin_entry_commit_spec",
    "read_update_status_snapshot",
    "revalidate_update_status",
    "update_status_snapshot_is_fresh",
    "write_update_status_snapshot",
]
