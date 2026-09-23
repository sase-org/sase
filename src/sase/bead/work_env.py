"""Launch-environment metadata for ``sase bead work`` automation."""

from __future__ import annotations

from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.bead.work_plan import EpicWorkPlan
from sase.bead.work_types import (
    EPIC_CLAN_SUMMARY_SCRIPT,
    EPIC_CLAN_TRIBE,
    SASE_BEAD_ID_ENV,
    SASE_EPIC_BEAD_ID_ENV,
    SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
    SASE_EPIC_PLAN_REF_ENV,
    SASE_EPIC_PLAN_SNAPSHOT_ENV,
    SASE_PHASE_BEAD_ID_ENV,
)


def epic_work_segment_env(
    plan: EpicWorkPlan,
    *,
    plan_ref: str,
    plan_snapshot: str | None = None,
    launch_names: frozenset[str] | None = None,
) -> tuple[dict[str, str], ...]:
    """Return role metadata for each epic-work launch segment.

    ``SASE_BEAD_ID`` remains the commit-attribution value for the child. The
    narrowly scoped epic fields are consumed while the child's
    ``agent_meta.json`` marker is written, giving ACE a plan/role association
    without overloading ``SASE_PLAN`` or consulting bead storage.
    """
    envs: list[dict[str, str]] = []
    for wave in plan.waves:
        for assignment in wave:
            if launch_names is not None and assignment.agent_name not in launch_names:
                continue
            env = _bead_env(
                assignment.bead_id,
                epic_id=plan.epic_id,
                plan_ref=plan_ref,
                plan_snapshot=plan_snapshot,
                phase_bead_id=assignment.bead_id,
            )
            if not envs:
                env[SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV] = EPIC_CLAN_SUMMARY_SCRIPT
            envs.append(env)
    if launch_names is None or plan.land_agent_name in launch_names:
        env = _bead_env(
            plan.epic_id,
            epic_id=plan.epic_id,
            plan_ref=plan_ref,
            plan_snapshot=plan_snapshot,
        )
        if not envs:
            env[SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV] = EPIC_CLAN_SUMMARY_SCRIPT
        envs.append(env)
    return tuple(envs)


def task_work_segment_env(bead_id: str) -> tuple[dict[str, str], ...]:
    """Return the single launch environment for a task-bead worker."""
    return (
        {
            SASE_BEAD_ID_ENV: bead_id,
            INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
        },
    )


def _bead_env(
    bead_id: str,
    *,
    epic_id: str,
    plan_ref: str,
    plan_snapshot: str | None = None,
    phase_bead_id: str | None = None,
) -> dict[str, str]:
    env = {
        SASE_BEAD_ID_ENV: bead_id,
        SASE_EPIC_BEAD_ID_ENV: epic_id,
        SASE_EPIC_CLAN_TRIBE_ENV: EPIC_CLAN_TRIBE,
        INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
    }
    if plan_ref:
        env[SASE_EPIC_PLAN_REF_ENV] = plan_ref
    if plan_snapshot:
        env[SASE_EPIC_PLAN_SNAPSHOT_ENV] = plan_snapshot
    if phase_bead_id:
        env[SASE_PHASE_BEAD_ID_ENV] = phase_bead_id
    return env


__all__ = [
    "_bead_env",
    "epic_work_segment_env",
    "task_work_segment_env",
]
