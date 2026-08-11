"""Composition for bead work actions."""

from __future__ import annotations

from ._artifacts_beads_issue_actions import ArtifactsBeadsIssueActionsMixin
from ._artifacts_beads_launch import ArtifactsBeadsLaunchActionsMixin


class ArtifactsBeadsWorkActionsMixin(
    ArtifactsBeadsLaunchActionsMixin,
    ArtifactsBeadsIssueActionsMixin,
):
    """Launch bead work and interact with linked tracker issues."""
