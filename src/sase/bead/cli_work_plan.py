"""Plan naming and display helpers for ``sase bead work``."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.bead.work import EpicWorkPlan


def expected_agent_names(plan: EpicWorkPlan) -> set[str]:
    names = {a.agent_name for wave in plan.waves for a in wave}
    names.add(plan.land_agent_name)
    return names


def _legacy_land_agent_name(plan: EpicWorkPlan) -> str | None:
    name = plan.epic_id
    if name == plan.land_agent_name:
        return None
    return name


def legacy_epic_cleanup_names(plan: EpicWorkPlan) -> frozenset[str]:
    """Return legacy deterministic owners to wipe that the prompt no longer names.

    Epic land agents now use ``<epic_id>.land``; older runs used ``<epic_id>``.
    The legacy name is not rendered in the new prompt, so it is an extra wipe
    target rather than an expected ``%id:!`` directive.
    """
    legacy = _legacy_land_agent_name(plan)
    return frozenset({legacy}) if legacy else frozenset()


def find_live_name_collisions(plan: EpicWorkPlan) -> dict[str, str]:
    """Return ``{agent_name: artifact_dir}`` for plan names owned by live agents."""
    from sase.agent.names import get_live_agent_name_subset

    expected = expected_agent_names(plan)
    legacy_land_name = _legacy_land_agent_name(plan)
    if legacy_land_name:
        expected.add(legacy_land_name)
    return get_live_agent_name_subset(expected)


def print_work_plan_summary(epic_id: str, title: str, plan: EpicWorkPlan) -> None:
    phase_count = sum(len(w) for w in plan.waves)
    wave_count = len(plan.waves)
    print(
        f"Epic {epic_id} — {title}: {phase_count} phase agent(s) in "
        f"{wave_count} wave(s) plus 1 land agent ({plan.land_agent_name})."
    )
    print(f"  Clan: {plan.epic_id} · Tribe: @epic")
    for i, wave in enumerate(plan.waves):
        names = ", ".join(f"{a.bead_id} → {a.agent_name}" for a in wave)
        print(f"  Wave {i}: {names}")
    if plan.land_waits_on:
        print(f"  Land waits on: {', '.join(plan.land_waits_on)}")


def confirm_launch() -> bool:
    answer = input("Launch these agents? [y/N] ").strip().lower()
    return answer in ("y", "yes")
