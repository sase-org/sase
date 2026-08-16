"""Agent loading and filtering logic for the ace TUI app.

The pure-data compute helpers (``_compute_loader_cleanup``,
``_compute_apply_loaded_agents``) live in :mod:`._loading_compute` so
they can run on a worker thread. The post-load finalize pipeline
(``finalize_agent_list``) lives in :mod:`._loading_finalize`.

This module remains the public import facade for
:class:`AgentLoadingMixin`; the implementation is split into narrow
private mixins so each file stays small and focused.
"""

from __future__ import annotations

from ._loading_apply import AgentLoadingApplyMixin
from ._loading_bead_warmup import AgentBeadWarmupMixin
from ._loading_compute import (
    _CLEANED_ARTIFACT_DIRS,
    compute_apply_loaded_agents,
    compute_loader_cleanup,
    PreparedApplyData,
    PreparedApplySnapshot,
)
from ._loading_diff_badges import AgentDiffBadgeMixin
from ._loading_disk import AgentLoadingDiskMixin
from ._loading_filter import AgentLoadingFilterMixin
from ._loading_family_previews import AgentFamilyPreviewMixin
from ._loading_helpers import (
    DISMISSABLE_STATUSES,
    load_agent_artifact_delta_from_disk_with_state,
    load_agents_from_disk_with_state,
)
from ._index_maintenance import AgentIndexMaintenanceMixin
from ._loading_live_hints import AgentLiveHintMixin
from ._loading_refresh import AgentLoadingRefreshMixin

# Aliases preserved so `_loading._compute_loader_cleanup` and
# `_loading._PreparedApplyData` keep working for the test suite that
# already pokes at these names via attribute access.
_compute_loader_cleanup = compute_loader_cleanup
_compute_apply_loaded_agents = compute_apply_loaded_agents
_PreparedApplyData = PreparedApplyData
_PreparedApplySnapshot = PreparedApplySnapshot

__all__ = [
    "AgentLoadingMixin",
    "DISMISSABLE_STATUSES",
    "_CLEANED_ARTIFACT_DIRS",
    "_compute_apply_loaded_agents",
    "_compute_loader_cleanup",
    "_PreparedApplyData",
    "_PreparedApplySnapshot",
    "load_agent_artifact_delta_from_disk_with_state",
    "load_agents_from_disk_with_state",
]


class AgentLoadingMixin(
    AgentLoadingDiskMixin,
    AgentIndexMaintenanceMixin,
    AgentLoadingApplyMixin,
    AgentLoadingRefreshMixin,
    AgentLoadingFilterMixin,
    AgentLiveHintMixin,
    AgentFamilyPreviewMixin,
    AgentBeadWarmupMixin,
    AgentDiffBadgeMixin,
):
    """Mixin providing agent loading and filtering methods."""
