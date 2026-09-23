"""DAG → wave plan → multi-prompt rendering for ``sase bead work`` automation.

Compatibility facade: the implementation now lives in :mod:`sase.bead.work_types`
(constants, launch contexts, base error), :mod:`sase.bead.work_plan`
(wave-plan construction), :mod:`sase.bead.work_prompt` (model directives and
multi-prompt rendering), and :mod:`sase.bead.work_env` (launch-environment
metadata). This module re-exports the previous public surface so existing
``from sase.bead.work import ...`` imports keep working; prefer the focused
modules for new code.
"""

from __future__ import annotations

from sase.bead.work_env import epic_work_segment_env, task_work_segment_env
from sase.bead.work_plan import EpicWorkPlan, build_epic_work_plan_from_beads_dir
from sase.bead.work_prompt import (
    epic_land_model_directive_value,
    phase_model_directive_value,
    phase_requires_plan,
    render_multi_prompt,
    render_task_prompt,
    task_model_directive_value,
)
from sase.bead.work_types import (
    EPIC_CLAN_SUMMARY_SCRIPT,
    EPIC_CLAN_TRIBE,
    EpicPlanError,
    PatchLaunchContext,
    SASE_BEAD_ID_ENV,
    SASE_EPIC_BEAD_ID_ENV,
    SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
    SASE_EPIC_PLAN_REF_ENV,
    SASE_EPIC_PLAN_SNAPSHOT_ENV,
    SASE_PHASE_BEAD_ID_ENV,
    VCSLaunchContext,
)

__all__ = [
    "EPIC_CLAN_SUMMARY_SCRIPT",
    "EPIC_CLAN_TRIBE",
    "EpicPlanError",
    "EpicWorkPlan",
    "PatchLaunchContext",
    "SASE_BEAD_ID_ENV",
    "SASE_EPIC_BEAD_ID_ENV",
    "SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV",
    "SASE_EPIC_CLAN_TRIBE_ENV",
    "SASE_EPIC_PLAN_REF_ENV",
    "SASE_EPIC_PLAN_SNAPSHOT_ENV",
    "SASE_PHASE_BEAD_ID_ENV",
    "VCSLaunchContext",
    "build_epic_work_plan_from_beads_dir",
    "epic_land_model_directive_value",
    "epic_work_segment_env",
    "phase_model_directive_value",
    "phase_requires_plan",
    "render_multi_prompt",
    "render_task_prompt",
    "task_model_directive_value",
    "task_work_segment_env",
]
