"""Human-readable rendering for plan-file bead work."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from sase.bead.cli_work_from_plan_types import PlanFileWorkResult

if TYPE_CHECKING:
    from sase.bead.work import EpicWorkPlan
    from sase.sdd.plan_validate import PlanValidationResult


def render_validation_failure(
    plan_path: Path,
    validation: PlanValidationResult,
) -> None:
    from sase.main.plan_validate_render import render_validation_human
    from sase.sdd.plan_validate import plan_frontmatter_schema

    render_validation_human(
        validation,
        tier="epic",
        path=str(plan_path),
        schema=plan_frontmatter_schema("epic"),
        console=Console(stderr=True),
    )


def render_plan_preview(
    plan: Any,
    waves: tuple[tuple[str, ...], ...],
) -> None:
    from sase.bead.work import (
        epic_land_model_directive_value,
        phase_model_directive_value,
    )

    phase_by_id = {phase.id: phase for phase in plan.phases}
    for index, wave in enumerate(waves, start=1):
        rendered_entries: list[str] = []
        for phase_id in wave:
            phase = phase_by_id[phase_id]
            model = phase_model_directive_value(phase.model, size=phase.size)
            plan_suffix = " · #plan" if phase.size in {"medium", "large"} else ""
            rendered_entries.append(
                f"{phase_id} {phase.title} ({phase.size} · {model}{plan_suffix})"
            )
        entries = "  |  ".join(rendered_entries)
        Console().print(f"  [bold]Wave {index}[/bold]  {entries}")
    land_model = epic_land_model_directive_value(
        plan.model,
        total_phase_count=len(plan.phases),
    )
    Console().print(f"  [bold]Land[/bold]    {land_model}")


def render_parent_preview(
    parent_id: str | None,
    preview_epic_id: str | None,
    *,
    overridden: bool,
) -> None:
    """Render the effective parent and prospective hierarchical epic ID."""
    if parent_id is None:
        if overridden:
            Console().print(
                "[green]✓[/green] Parent          top-level (explicit override)"
            )
        return
    Console().print(
        f"[green]✓[/green] Parent          {parent_id} · preview epic {preview_epic_id}"
    )


def render_created_beads(
    issue: Any,
    phases: list[Any],
    work_plan: EpicWorkPlan,
    archived_path: Path,
) -> None:
    Console().print(f"[green]✓[/green] Epic bead       {issue.id} — {issue.title}")
    phase_text = " · ".join(f"{phase.id} {phase.title}" for phase in phases)
    Console().print(f"[green]✓[/green] Phase beads     {phase_text}")
    dependency_count = sum(len(phase.dependencies) for phase in phases)
    Console().print(
        f"[green]✓[/green] Dependencies    {dependency_count} edges · "
        f"{len(work_plan.waves)} waves"
    )
    Console().print(
        f"[green]✓[/green] Plan linked     bead_id: {issue.id} · {archived_path}"
    )


def render_final(result: PlanFileWorkResult) -> None:
    assert result.epic_id is not None
    if result.launched:
        Console().print(
            f"\nEpic {result.epic_id} is underway — track it on the Agents tab, "
            f"or run:\n  sase bead show {result.epic_id}"
        )
    else:
        Console().print(f"\nEpic {result.epic_id} launch was not started.")
    print(f"Epic: {result.epic_id}")
