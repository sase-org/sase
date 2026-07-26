"""Shared data models and prompt scaffolding for chop proposals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PreparedChopProposal:
    index: int
    proposal_id: str | None
    prompt: str
    workspace: str
    agent_name: str
    explicit_agent_name: bool
    clan: str | None
    clan_summary: str | None
    tribe: str
    model: str | None
    effort: str | None
    env: dict[str, str]
    dedupe_key: str | None
    wait_on: int | str | None


@dataclass(frozen=True)
class PlannedChopProposal:
    """One side-effect-free proposal scaffold ready for preview or launch."""

    proposal: PreparedChopProposal
    agent_name: str
    clan: str | None
    member_id: str | None
    declares_clan: bool
    clan_summary: str | None
    prompt: str


def full_name_template(proposal: PreparedChopProposal) -> str:
    if proposal.clan is None:
        return proposal.agent_name
    return f"{proposal.clan}.{proposal.agent_name}"


def scaffolded_prompt(
    proposal: PreparedChopProposal,
    wait_name: str | None,
    *,
    agent_name: str | None = None,
    clan: str | None = None,
    member_id: str | None = None,
    declares_clan: bool = False,
    clan_summary: str | None = None,
) -> str:
    """Build the complete launch prompt for a prepared proposal."""
    resolved_name = agent_name or full_name_template(proposal)
    resolved_clan = clan if proposal.clan is not None else None
    workspace = (
        proposal.workspace
        if proposal.workspace.startswith("#")
        else f"#{proposal.workspace}"
    )
    lines = [workspace]
    if resolved_clan is not None:
        resolved_member = member_id or proposal.agent_name
        if declares_clan:
            declaration = f"%clan({resolved_clan}, tribe=chop)"
            if clan_summary is not None:
                declaration = (
                    f"%clan({resolved_clan}, tribe=chop, summary=[[{clan_summary}]])"
                )
            lines.extend([f"%id:{resolved_name}", declaration])
        else:
            lines.append(f"%id({resolved_member}, clan={resolved_clan})")
    else:
        lines.append(f"%id({resolved_name}, tribe={proposal.tribe})")
    if proposal.model:
        lines.append(f"%model:{proposal.model}")
    if proposal.effort:
        lines.append(f"%effort:{proposal.effort}")
    if wait_name:
        lines.append(f"%wait:{wait_name}")
    lines.append(proposal.prompt.strip())
    return "\n".join(lines) + "\n"


def resolve_wait_name(
    wait_on: int | str | None,
    names_by_index: Mapping[int, str],
    names_by_id: Mapping[str, str],
) -> str | None:
    """Resolve a proposal wait reference to its planned or launched name."""
    if wait_on is None:
        return None
    if isinstance(wait_on, int):
        return names_by_index[wait_on]
    return names_by_id[wait_on]


__all__ = [
    "PlannedChopProposal",
    "PreparedChopProposal",
    "full_name_template",
    "resolve_wait_name",
    "scaffolded_prompt",
]
