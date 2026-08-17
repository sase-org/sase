"""Plan naming and display helpers for ``sase bead work``."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.bead.cli_work_cleanup import BeadWorkSlot
    from sase.bead.cli_work_cleanup import CleanupPreview
    from sase.bead.work import EpicWorkPlan


def expected_agent_names(plan: EpicWorkPlan) -> set[str]:
    names = {a.agent_name for wave in plan.waves for a in wave}
    names.add(plan.land_agent_name)
    return names


def bead_work_slots(plan: EpicWorkPlan) -> tuple[BeadWorkSlot, ...]:
    from sase.bead.cli_work_cleanup import BeadWorkSlot

    slots: list[BeadWorkSlot] = [
        BeadWorkSlot(
            slot_id=assignment.agent_name,
            owner_name=assignment.agent_name,
            expected_bead_id=assignment.bead_id,
            launch_name=assignment.agent_name,
        )
        for wave in plan.waves
        for assignment in wave
    ]
    slots.append(
        BeadWorkSlot(
            slot_id=f"{plan.epic_id}:land",
            owner_name=plan.land_agent_name,
            expected_bead_id=plan.epic_id,
            launch_name=plan.land_agent_name,
        )
    )
    legacy = _legacy_land_agent_name(plan)
    if legacy is not None:
        slots.append(
            BeadWorkSlot(
                slot_id=f"{plan.epic_id}:land",
                owner_name=legacy,
                expected_bead_id=plan.epic_id,
                launch_name=plan.land_agent_name,
                allow_populated_clan_skip=True,
            )
        )
    return tuple(slots)


def _legacy_land_agent_name(plan: EpicWorkPlan) -> str | None:
    name = plan.epic_id
    if name == plan.land_agent_name:
        return None
    return name


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


def print_task_work_summary(
    task_id: str,
    title: str,
    *,
    model: str,
) -> None:
    """Print the deterministic one-worker task launch plan."""
    print(f"Task {task_id} — {title}: 1 agent ({task_id}) using {model}.")


def render_cleanup_preview(epic_id: str, preview: CleanupPreview) -> None:
    """Print an itemized destructive-cleanup preview to stderr."""
    if not preview.targets:
        return
    print(
        f"\nExisting agents for epic {epic_id}:",
        file=sys.stderr,
    )
    action_order = {
        "BLOCKED": 0,
        "PRESERVE": 1,
        "KILL": 2,
        "REMOVE": 3,
        "RELEASE": 4,
    }
    for target in sorted(
        preview.targets,
        key=lambda item: (action_order[item.action], item.name),
    ):
        bead = f" bead={target.expected_bead_id}" if target.expected_bead_id else ""
        print(
            f"  {target.action:<8} ({target.current_state}) "
            f"{target.name}{bead}  {target.detail}",
            file=sys.stderr,
        )


def render_task_cleanup_preview(task_id: str, preview: CleanupPreview) -> None:
    """Print an itemized task-agent cleanup preview to stderr."""
    if not preview.targets:
        return
    print(
        f"\nExisting agent for task {task_id}:",
        file=sys.stderr,
    )
    action_order = {
        "BLOCKED": 0,
        "PRESERVE": 1,
        "KILL": 2,
        "REMOVE": 3,
        "RELEASE": 4,
    }
    for target in sorted(
        preview.targets,
        key=lambda item: (action_order[item.action], item.name),
    ):
        bead = f" bead={target.expected_bead_id}" if target.expected_bead_id else ""
        print(
            f"  {target.action:<8} ({target.current_state}) "
            f"{target.name}{bead}  {target.detail}",
            file=sys.stderr,
        )


def render_blocked_launch_warning(blocked_count: int) -> None:
    """Print how many blockers would abort a real launch."""
    if blocked_count <= 0:
        return
    noun = "blocker" if blocked_count == 1 else "blockers"
    print(
        f"{blocked_count} {noun} would abort a real launch.",
        file=sys.stderr,
    )


def _confirm(prompt: str) -> bool | None:
    """Return ``None`` when confirmation cannot be requested interactively."""
    if not sys.stdin.isatty():
        return None
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def confirm_cleanup() -> bool | None:
    """Confirm destructive teardown, or return ``None`` for non-TTY stdin."""
    return _confirm("Proceed with dismissing/killing these agents? [y/N] ")


def confirm_launch() -> bool | None:
    """Confirm launch, or return ``None`` for non-TTY stdin."""
    return _confirm("Launch these agents? [y/N] ")
