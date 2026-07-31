"""Plan naming and display helpers for ``sase bead work``."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.bead.cli_work_cleanup import CleanupPreview
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
    if not preview.has_destructive_targets:
        return
    print(
        f"\nCleaning up existing agents before relaunching epic {epic_id}:",
        file=sys.stderr,
    )
    action_order = {"KILL": 0, "REMOVE": 1, "RELEASE": 2}
    for target in sorted(
        preview.targets,
        key=lambda item: (action_order[item.action], item.name),
    ):
        print(
            f"  {target.action:<7} ({target.current_state}) "
            f"{target.name}  {target.detail}",
            file=sys.stderr,
        )


def render_task_cleanup_preview(task_id: str, preview: CleanupPreview) -> None:
    """Print an itemized task-agent cleanup preview to stderr."""
    if not preview.has_destructive_targets:
        return
    print(
        f"\nCleaning up the existing agent before relaunching task {task_id}:",
        file=sys.stderr,
    )
    action_order = {"KILL": 0, "REMOVE": 1, "RELEASE": 2}
    for target in sorted(
        preview.targets,
        key=lambda item: (action_order[item.action], item.name),
    ):
        print(
            f"  {target.action:<7} ({target.current_state}) "
            f"{target.name}  {target.detail}",
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
