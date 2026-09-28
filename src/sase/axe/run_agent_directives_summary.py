"""Clan summary resolution stage for the run agent runner.

Resolves the explicit clan summary (declared or epic-propagated) and the
inherited summary defaults for a new clan generation. Mutates ``agent_meta``
with any resolved ``clan_summary`` value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.axe.run_agent_directive_clans import (
    ClanSummaryResolutionRequest,
    apply_clan_launch_defaults,
)


@dataclass(frozen=True)
class ClanSummaryOutcome:
    """Resolved clan summary inputs for the post-preparation summary run."""

    resolution: ClanSummaryResolutionRequest | None
    explicit_summary: str | None
    explicit_script: str | None


def resolve_clan_summary_outcome(
    *,
    directives: Any,
    clan_membership_plan: Any | None,
    epic_clan_summary_script: str | None,
    epic_work_metadata: dict[str, Any],
    preserved_metadata: dict[str, Any],
    agent_meta: dict[str, Any],
    workspace_dir: str,
    output_path: str | None,
    artifacts_dir: str,
    launch_environment: dict[str, str],
) -> ClanSummaryOutcome:
    """Resolve explicit and inherited clan summaries for this launch."""
    explicit_resolution: ClanSummaryResolutionRequest | None = None
    explicit_summary: str | None = None
    explicit_script: str | None = None

    if clan_membership_plan and (directives.clan_declared or epic_clan_summary_script):
        from sase.axe.clan_summary_script import (
            normalize_clan_summary,
            resolve_clan_summary_script,
        )

        clan_summary = (
            normalize_clan_summary(directives.clan_summary or "")
            if directives.clan_declared
            else None
        )
        summary_script = directives.clan_summary_script
        if not directives.clan_declared and epic_clan_summary_script:
            summary_script = epic_clan_summary_script
        if summary_script:
            clan_tribe = directives.clan_tribe
            if not directives.clan_declared and clan_tribe is None:
                epic_clan_tribe = epic_work_metadata.get("clan_tribe")
                if isinstance(epic_clan_tribe, str) and epic_clan_tribe:
                    clan_tribe = epic_clan_tribe
            explicit_resolution = ClanSummaryResolutionRequest(
                script=summary_script,
                clan_name=clan_membership_plan.clan_name,
                clan_generation=clan_membership_plan.generation,
                clan_tribe=clan_tribe,
            )
            clan_summary = resolve_clan_summary_script(
                summary_script,
                workspace_dir=workspace_dir,
                clan_name=clan_membership_plan.clan_name,
                clan_generation=clan_membership_plan.generation,
                clan_tribe=clan_tribe,
                agent_log_path=output_path,
                artifacts_dir=artifacts_dir,
                environment=launch_environment,
            )
        if clan_summary:
            agent_meta["clan_summary"] = clan_summary
        explicit_summary = clan_summary
        explicit_script = summary_script

    inherited_resolution: ClanSummaryResolutionRequest | None = None
    inherited_summary: str | None = None
    inherited_script: str | None = None
    if clan_membership_plan is not None:
        (
            inherited_resolution,
            inherited_summary,
            inherited_script,
        ) = apply_clan_launch_defaults(
            artifacts_dir=artifacts_dir,
            workspace_dir=workspace_dir,
            output_path=output_path,
            launch_environment=launch_environment,
            clan_membership_plan=clan_membership_plan,
            directives=directives,
            epic_work_metadata=epic_work_metadata,
            epic_clan_summary_script=epic_clan_summary_script,
            preserved_metadata=preserved_metadata,
            agent_meta=agent_meta,
        )

    clan_summary_resolution = (
        inherited_resolution
        if inherited_resolution is not None
        else explicit_resolution
    )
    return ClanSummaryOutcome(
        resolution=clan_summary_resolution,
        explicit_summary=explicit_summary,
        explicit_script=explicit_script,
    )


__all__ = ["ClanSummaryOutcome", "resolve_clan_summary_outcome"]
