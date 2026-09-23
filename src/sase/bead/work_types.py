"""Shared constants and launch contexts for ``sase bead work`` automation.

Wave-plan types live in :mod:`sase.bead.work_plan` next to the builder that
constructs them; prompt rendering lives in :mod:`sase.bead.work_prompt`; launch
metadata lives in :mod:`sase.bead.work_env`. This module keeps only the pieces
with no construction logic so every name here is public and freely imported
across files.
"""

from __future__ import annotations

from dataclasses import dataclass

SASE_BEAD_ID_ENV = "SASE_BEAD_ID"
SASE_EPIC_PLAN_REF_ENV = "SASE_EPIC_PLAN_REF"
SASE_EPIC_PLAN_SNAPSHOT_ENV = "SASE_EPIC_PLAN_SNAPSHOT"
SASE_EPIC_BEAD_ID_ENV = "SASE_EPIC_BEAD_ID"
SASE_EPIC_CLAN_TRIBE_ENV = "SASE_EPIC_CLAN_TRIBE"
SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV = "SASE_EPIC_CLAN_SUMMARY_SCRIPT"
SASE_PHASE_BEAD_ID_ENV = "SASE_PHASE_BEAD_ID"
EPIC_CLAN_TRIBE = "epic"
EPIC_CLAN_SUMMARY_SCRIPT = "sase_clan_summary_epic"


@dataclass(frozen=True)
class VCSLaunchContext:
    """VCS launch wrapper for project-scoped epic work."""

    vcs_workflow: str
    project_name: str


@dataclass(frozen=True)
class PatchLaunchContext(VCSLaunchContext):
    """VCS launch wrapper for Patch-attached epic work."""

    changespec_name: str
    bug_id: str = ""


class EpicPlanError(ValueError):
    """Base error for epic-work-plan construction failures."""


__all__ = [
    "EPIC_CLAN_SUMMARY_SCRIPT",
    "EPIC_CLAN_TRIBE",
    "EpicPlanError",
    "PatchLaunchContext",
    "SASE_BEAD_ID_ENV",
    "SASE_EPIC_BEAD_ID_ENV",
    "SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV",
    "SASE_EPIC_CLAN_TRIBE_ENV",
    "SASE_EPIC_PLAN_REF_ENV",
    "SASE_EPIC_PLAN_SNAPSHOT_ENV",
    "SASE_PHASE_BEAD_ID_ENV",
    "VCSLaunchContext",
]
