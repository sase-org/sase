"""Generated skill deployment checks for ``sase doctor``."""

from __future__ import annotations

from typing import Any

from sase.config.core import get_use_chezmoi
from sase.diagnostics import DiagnosticCheck
from sase.skills.inventory import (
    AppliedSkillsInventory,
    AppliedSkillTargetEntry,
    build_applied_skills_inventory,
)

_DRIFT_DETAIL_LIMIT = 8


def check_config_skills_applied(
    *,
    use_chezmoi: bool | None = None,
    inventory: AppliedSkillsInventory | None = None,
) -> DiagnosticCheck:
    """Check live home skill targets against chezmoi source skill files."""
    if use_chezmoi is None:
        use_chezmoi = get_use_chezmoi()

    if not use_chezmoi:
        return DiagnosticCheck(
            id="config.skills.applied",
            group="config",
            status="SKIP",
            title="Applied generated skills",
            summary="chezmoi skill deployment is disabled",
            data={"use_chezmoi": False},
        )

    inventory = inventory or build_applied_skills_inventory()
    data = _applied_skills_data(inventory, use_chezmoi=use_chezmoi)
    if inventory.target_count == 0:
        return DiagnosticCheck(
            id="config.skills.applied",
            group="config",
            status="SKIP",
            title="Applied generated skills",
            summary="no generated skill targets are configured",
            data=data,
        )

    drift = inventory.drift_targets
    if not drift:
        return DiagnosticCheck(
            id="config.skills.applied",
            group="config",
            status="OK",
            title="Applied generated skills",
            summary=(
                f"{inventory.target_count} applied home skill target(s) match "
                "the chezmoi source"
            ),
            data=data,
        )

    return DiagnosticCheck(
        id="config.skills.applied",
        group="config",
        status="WARN",
        title="Applied generated skills",
        summary=(
            f"{len(drift)}/{inventory.target_count} applied home skill target(s) "
            "diverge from the chezmoi source"
        ),
        details=tuple(
            _applied_skill_detail(target) for target in drift[:_DRIFT_DETAIL_LIMIT]
        ),
        next_steps=_applied_skill_next_steps(drift),
        data=data,
    )


def _applied_skills_data(
    inventory: AppliedSkillsInventory,
    *,
    use_chezmoi: bool,
) -> dict[str, Any]:
    return {
        "use_chezmoi": use_chezmoi,
        "target_count": inventory.target_count,
        "current_count": inventory.current_count,
        "stale_count": inventory.stale_count,
        "missing_count": inventory.missing_count,
        "source_missing_count": inventory.source_missing_count,
        "retired_count": inventory.retired_count,
        "prettier_available": inventory.prettier_available,
        "targets": tuple(_applied_skill_row(target) for target in inventory.targets),
    }


def _applied_skill_row(target: AppliedSkillTargetEntry) -> dict[str, str]:
    return {
        "provider": target.provider,
        "skill_name": target.skill_name,
        "status": target.status,
        "source_status": target.source_status,
        "source_path": str(target.source_path),
        "home_path": str(target.home_path),
    }


def _applied_skill_detail(target: AppliedSkillTargetEntry) -> str:
    return (
        f"{target.provider}/{target.skill_name}: {target.status} "
        f"(source: {target.source_path}; home: {target.home_path})"
    )


def _applied_skill_next_steps(
    drift: tuple[AppliedSkillTargetEntry, ...],
) -> tuple[str, ...]:
    steps: list[str] = []
    if any(target.status in {"missing", "stale"} for target in drift):
        steps.append(
            "Run `chezmoi apply` to update live home skill files from the chezmoi source."
        )
    if any(
        target.status != "retired"
        and (target.status == "source_missing" or target.source_status != "current")
        for target in drift
    ):
        steps.append(
            "Run `sase skill init --force`, then `chezmoi apply`, if generated source skill files are stale or missing."
        )
    if any(target.status == "retired" for target in drift):
        steps.append(
            "Run a full `sase skill init --force` deployment to remove retired generated skills."
        )
    return tuple(steps)


__all__ = ["check_config_skills_applied"]
