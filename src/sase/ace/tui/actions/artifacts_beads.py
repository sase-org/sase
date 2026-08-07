"""Composition and public exports for the Artifacts Beads pane actions."""

from __future__ import annotations

from ._artifacts_beads_browse import ArtifactsBeadsBrowseActionsMixin
from ._artifacts_beads_common import (
    ArtifactsBeadsCommonMixin,
    launch_scoped_epic as _launch_scoped_epic,
    next_bead_status as _next_bead_status,
    resolve_issue_url as _resolve_issue_url,
    unclosed_descendant_ids as _unclosed_descendant_ids,
)
from ._artifacts_beads_mutations import ArtifactsBeadsMutationActionsMixin
from ._artifacts_beads_work import ArtifactsBeadsWorkActionsMixin


BEADS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "beads_next",
        "beads_prev",
        "beads_view_selected",
        "beads_filters",
        "beads_expand",
        "beads_collapse",
        "beads_cycle_status",
        "beads_edit",
        "beads_add_note",
        "beads_create",
        "beads_close",
        "beads_snooze",
        "beads_launch_work",
        "beads_open_bug",
        "beads_open_plan",
        "beads_refresh",
    }
)


class ArtifactsBeadsActionsMixin(
    ArtifactsBeadsBrowseActionsMixin,
    ArtifactsBeadsMutationActionsMixin,
    ArtifactsBeadsWorkActionsMixin,
    ArtifactsBeadsCommonMixin,
):
    """Browse and mutate bead work items without blocking Textual's pump."""


__all__ = [
    "ArtifactsBeadsActionsMixin",
    "BEADS_ARTIFACT_ACTIONS",
    "_next_bead_status",
    "_resolve_issue_url",
    "_unclosed_descendant_ids",
]
