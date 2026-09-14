"""Disk-loading entry points for :class:`AgentLoadingMixin`.

This module remains the compatibility facade for tests and callers that
patch private disk-loading helpers. The implementation lives in narrower
modules split by responsibility.
"""

from __future__ import annotations

from ._loading_compute import compute_loader_cleanup as compute_loader_cleanup
from ._loading_disk_delta import AgentLoadingDiskDeltaMixin
from ._loading_disk_full import AgentLoadingDiskFullMixin
from ._loading_disk_io import (
    disk_load_with_optional_current_project as _disk_load_with_optional_current_project,
    resolve_load_agents_from_disk_with_state as _resolve_load_agents_from_disk_with_state,
)
from ._loading_disk_support import (
    AgentLoadingDiskSupportMixin,
    compute_external_dismissal_merge as _compute_external_dismissal_merge,
    ExternalDismissalMergeResult as _ExternalDismissalMergeResult,
)
from ._loading_disk_viewport import (
    AgentLoadingDiskViewportMixin,
    agent_load_query_is_stale as _agent_load_query_is_stale,
    agents_viewport_for_load as _agents_viewport_for_load,
    agents_viewport_request_key as _agents_viewport_request_key,
    current_agents_history_query_key as _current_agents_history_query_key,
    reschedule_stale_agent_query_load as _reschedule_stale_agent_query_load,
)
from ._search_query_seed import AgentSearchQuerySeedMixin

__all__ = [
    "AgentLoadingDiskMixin",
    "AgentLoadingDiskViewportMixin",
    "_ExternalDismissalMergeResult",
    "_agent_load_query_is_stale",
    "_agents_viewport_for_load",
    "_agents_viewport_request_key",
    "_compute_external_dismissal_merge",
    "_current_agents_history_query_key",
    "_disk_load_with_optional_current_project",
    "_resolve_load_agents_from_disk_with_state",
    "_reschedule_stale_agent_query_load",
    "compute_loader_cleanup",
]


class AgentLoadingDiskMixin(
    AgentLoadingDiskFullMixin,
    AgentLoadingDiskDeltaMixin,
    AgentSearchQuerySeedMixin,
    AgentLoadingDiskSupportMixin,
):
    """Methods that read agent state from disk and prepare apply snapshots."""
