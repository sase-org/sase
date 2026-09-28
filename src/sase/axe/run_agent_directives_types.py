"""Result types for run-agent directive extraction."""

from __future__ import annotations

from typing import Any, NamedTuple, TYPE_CHECKING

from sase.axe.run_agent_directive_clans import ClanSummaryResolutionRequest

if TYPE_CHECKING:
    from sase.xprompt.hold_directive import HoldFields


class AgentInfo(NamedTuple):
    """Result of directive extraction and metadata writing."""

    name: str | None
    bead_id: str | None
    wait_names: list[str]
    wait_identity_deps: list[dict[str, Any]]
    wait_fork_sources: list[dict[str, str]]
    wait_beads: list[str]
    wait_hoods: list[str]
    wait_duration: float | None
    wait_until: str | None
    wait_runners: int | None
    queue_capacity_multiplier: float | None
    wait_priority: int | None
    queue_weight: float
    queue_weight_explicit: bool
    model: str | None
    llm_provider: str | None
    vcs_provider: str | None
    hidden: bool
    approve: bool
    plan: bool
    tribe: str | None
    clan_summary_resolution: ClanSummaryResolutionRequest | None
    meta: dict[str, Any]
    local_xprompts: dict[str, Any]
    hold: HoldFields | None = None


__all__ = ["AgentInfo"]
