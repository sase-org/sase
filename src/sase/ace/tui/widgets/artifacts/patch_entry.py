"""Stable row identity for the Artifacts Patches pane."""

from __future__ import annotations

from sase.ace.patch import Patch

from .entry_navigation import ArtifactEntryTarget


def patch_row_target(patch: Patch) -> ArtifactEntryTarget:
    """Return the cross-refresh identity for one Patch row."""
    return ArtifactEntryTarget(
        pane_id="patches",
        parts=(patch.project_name, patch.name),
    )


__all__ = ["patch_row_target"]
