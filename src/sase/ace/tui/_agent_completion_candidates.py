"""Construction and filtering of visible-agent completion candidates."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sase.ace.tui._agent_completion_models import AgentCompletionCandidate
from sase.ace.tui._agent_completion_prompt import (
    prompt_snippet,
    raw_vcs_tag_for_prompt,
    vcs_workflow_from_prompt,
)

if TYPE_CHECKING:
    from sase.ace.tui.models import Agent


@dataclass(frozen=True, slots=True)
class _ClanCompletionGroup:
    """Newest visible generation of one clan, derived without external reads."""

    name: str
    generation: str | None
    source_index: int
    container: Agent | None
    members: tuple[Agent, ...]
    tags: tuple[str, ...]


def agent_prompt_name(agent: Agent) -> str | None:
    """Return the prompt-referenceable name for an agent row."""
    if agent.is_family_root_entry:
        return agent.family_reference_name()
    return agent.agent_name


def build_agent_completion_candidates(
    visible_agents: Iterable[Agent],
    *,
    exclude_identity: object | None = None,
) -> list[AgentCompletionCandidate]:
    """Build kind-aware completion candidates from one visible-row snapshot."""
    all_agents = list(visible_agents)
    clan_groups = visible_clan_completion_groups(all_agents)
    clans = _build_clan_completion_candidates(
        clan_groups,
        exclude_identity=exclude_identity,
    )
    families = _build_family_completion_candidates(
        all_agents,
        exclude_identity=exclude_identity,
    )
    agents = _build_plain_agent_completion_candidates(
        all_agents,
        exclude_identity=exclude_identity,
    )
    tribes = _build_tribe_completion_candidates(all_agents, clan_groups)
    return _dedupe_completion_candidates([*tribes, *clans, *families, *agents])


def _dedupe_completion_candidates(
    candidates: Iterable[AgentCompletionCandidate],
) -> list[AgentCompletionCandidate]:
    ordered: list[AgentCompletionCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.name in seen:
            continue
        seen.add(candidate.name)
        ordered.append(candidate)
    return ordered


def _build_plain_agent_completion_candidates(
    all_agents: Sequence[Agent],
    *,
    exclude_identity: object | None,
) -> list[AgentCompletionCandidate]:
    """Return real, non-container rows in their existing visible order."""
    candidates: list[AgentCompletionCandidate] = []
    seen_names: set[str] = set()
    for agent in all_agents:
        if (
            agent.is_clan_container
            or agent.is_synthetic_planner
            or agent.is_family_root_entry
            or (exclude_identity is not None and agent.identity == exclude_identity)
        ):
            continue
        name = agent_prompt_name(agent)
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        candidates.append(_candidate_from_agent(agent, name, all_agents))
    return candidates


def filter_agent_completion_candidates(
    candidates: Sequence[AgentCompletionCandidate] | None,
    partial: str,
) -> list[AgentCompletionCandidate]:
    """Return prompt-target candidates matching *partial* by name prefix."""
    if not candidates:
        return []
    partial_lower = partial.lower()
    return [
        candidate
        for candidate in candidates
        if _candidate_matches_prefix(candidate, partial_lower)
    ]


def _candidate_matches_prefix(
    candidate: AgentCompletionCandidate,
    partial_lower: str,
) -> bool:
    if candidate.kind != "tribe" or partial_lower.startswith("@"):
        return candidate.name.lower().startswith(partial_lower)
    return candidate.name.removeprefix("@").lower().startswith(partial_lower)


def visible_clan_completion_groups(
    all_agents: Sequence[Agent],
) -> list[_ClanCompletionGroup]:
    """Return each clan's newest visible generation in stable display order."""
    rows_by_key: dict[tuple[str, str | None], list[tuple[int, Agent]]] = {}
    for index, agent in enumerate(all_agents):
        if not agent.agent_clan:
            continue
        key = (agent.agent_clan, agent.agent_clan_generation)
        rows_by_key.setdefault(key, []).append((index, agent))

    groups_by_name: dict[str, list[_ClanCompletionGroup]] = {}
    for (name, generation), indexed_rows in rows_by_key.items():
        rows = [row for _index, row in indexed_rows]
        container = next((row for row in rows if row.is_clan_container), None)
        members = _clan_group_members(container, rows)
        if not members:
            continue
        groups_by_name.setdefault(name, []).append(
            _ClanCompletionGroup(
                name=name,
                generation=generation,
                source_index=min(index for index, _row in indexed_rows),
                container=container,
                members=members,
                tags=_clan_group_tags(container, rows),
            )
        )

    newest = [
        max(groups, key=_clan_group_recency_key) for groups in groups_by_name.values()
    ]
    newest.sort(key=lambda group: group.source_index)
    return newest


def _clan_group_recency_key(group: _ClanCompletionGroup) -> tuple[str, str]:
    row_recency = max((_agent_recency_key(row) for row in group.members), default="")
    return (group.generation or row_recency, row_recency)


def _agent_recency_key(agent: Agent) -> str:
    if agent.raw_suffix:
        return agent.raw_suffix
    if agent.start_time is not None:
        return agent.start_time.isoformat()
    return ""


def _clan_group_members(
    container: Agent | None,
    rows: Sequence[Agent],
) -> tuple[Agent, ...]:
    if container is not None:
        from sase.ace.tui.models._agent_clan_sections import clan_section_member_rows

        members = clan_section_member_rows(container)
        if members:
            return _dedupe_real_member_rows(members)
    return _dedupe_real_member_rows(row for row in rows if not row.is_clan_container)


def _clan_group_tags(
    container: Agent | None,
    rows: Sequence[Agent],
) -> tuple[str, ...]:
    tags: list[str] = []
    if container is not None:
        tags.extend(container.clan_tags)
        if container.clan_tribe:
            tags.append(container.clan_tribe)
        if container.tag:
            tags.append(container.tag)
    if not tags:
        tags.extend(row.clan_tribe or row.tag or "" for row in rows)
    return tuple(dict.fromkeys(tag for tag in tags if tag))


def _build_clan_completion_candidates(
    groups: Sequence[_ClanCompletionGroup],
    *,
    exclude_identity: object | None,
) -> list[AgentCompletionCandidate]:
    candidates: list[AgentCompletionCandidate] = []
    for group in groups:
        if exclude_identity is not None and any(
            member.identity == exclude_identity for member in group.members
        ):
            continue
        status = _aggregate_completion_status(group.members)
        candidates.append(
            AgentCompletionCandidate(
                name=group.name,
                label=group.name,
                status=status,
                kind="clan",
                member_count=len(group.members),
                aggregate_status=status,
                member_names=_member_names(group.members),
            )
        )
    return candidates


def _build_family_completion_candidates(
    all_agents: Sequence[Agent],
    *,
    exclude_identity: object | None,
) -> list[AgentCompletionCandidate]:
    from sase.ace.tui.models.agent_family_members import concrete_family_member_rows

    candidates: list[AgentCompletionCandidate] = []
    seen_names: set[str] = set()
    for agent in all_agents:
        if not agent.is_family_root_entry or agent.is_clan_container:
            continue
        name = agent.family_reference_name()
        if not name or name in seen_names:
            continue
        members = _dedupe_real_member_rows(concrete_family_member_rows(agent))
        if not members or (
            exclude_identity is not None
            and any(member.identity == exclude_identity for member in members)
        ):
            continue
        seen_names.add(name)
        status = _aggregate_completion_status(members)
        candidates.append(
            _candidate_from_agent(
                agent,
                name,
                all_agents,
                kind="family",
                member_count=len(members),
                aggregate_status=status,
                member_names=_member_names(members),
            )
        )
    return candidates


def _build_tribe_completion_candidates(
    all_agents: Sequence[Agent],
    clan_groups: Sequence[_ClanCompletionGroup],
) -> list[AgentCompletionCandidate]:
    """Build canonical ``@tribe`` targets from already-loaded rows and clans."""
    from sase.ace.tui.models.agent_family_members import concrete_family_member_rows

    clan_group_by_key = {(group.name, group.generation): group for group in clan_groups}
    encountered_clans: set[tuple[str, str | None]] = set()
    members_by_tribe: dict[str, list[Agent]] = {}
    agent_carriers_by_tribe: dict[str, set[object]] = {}
    clan_carriers_by_tribe: dict[str, set[tuple[str, str | None]]] = {}
    tribe_order: list[str] = []

    def add(
        tag: str,
        members: Iterable[Agent],
        *,
        agent_carrier: object | None = None,
        clan_carrier: tuple[str, str | None] | None = None,
    ) -> None:
        bare_tag = tag.removeprefix("@")
        if not bare_tag:
            return
        if bare_tag not in members_by_tribe:
            members_by_tribe[bare_tag] = []
            agent_carriers_by_tribe[bare_tag] = set()
            clan_carriers_by_tribe[bare_tag] = set()
            tribe_order.append(bare_tag)
        members_by_tribe[bare_tag].extend(members)
        if agent_carrier is not None:
            agent_carriers_by_tribe[bare_tag].add(agent_carrier)
        if clan_carrier is not None:
            clan_carriers_by_tribe[bare_tag].add(clan_carrier)

    for agent in all_agents:
        if agent.agent_clan:
            key = (agent.agent_clan, agent.agent_clan_generation)
            group = clan_group_by_key.get(key)
            if group is None or key in encountered_clans:
                continue
            encountered_clans.add(key)
            for tag in group.tags:
                add(tag, group.members, clan_carrier=key)
            continue
        if agent.is_clan_container or agent.is_synthetic_planner or not agent.tag:
            continue
        members: Iterable[Agent]
        if agent.is_family_root_entry:
            members = concrete_family_member_rows(agent)
        else:
            members = (agent,)
        add(agent.tag, members, agent_carrier=agent.identity)

    candidates: list[AgentCompletionCandidate] = []
    for tag in tribe_order:
        members = _dedupe_real_member_rows(members_by_tribe[tag])
        if not members:
            continue
        status = _aggregate_completion_status(members)
        candidates.append(
            AgentCompletionCandidate(
                name=f"@{tag}",
                label=tag,
                status=status,
                kind="tribe",
                member_count=len(members),
                aggregate_status=status,
                member_names=_member_names(members),
                agent_count=len(agent_carriers_by_tribe[tag]),
                clan_count=len(clan_carriers_by_tribe[tag]),
                search_aliases=(tag,),
            )
        )
    return candidates


def _dedupe_real_member_rows(rows: Iterable[Agent]) -> tuple[Agent, ...]:
    members: list[Agent] = []
    seen: set[object] = set()
    for row in rows:
        if row.is_clan_container or row.is_synthetic_planner or row.identity in seen:
            continue
        seen.add(row.identity)
        members.append(row)
    return tuple(members)


def _aggregate_completion_status(rows: Sequence[Agent]) -> str:
    from sase.ace.tui.models._agent_clan import aggregate_clan_status

    return aggregate_clan_status(row.status for row in rows) or "RUNNING"


def _member_names(rows: Sequence[Agent]) -> tuple[str, ...]:
    names: list[str] = []
    for row in rows:
        name = row.agent_name or row.presented_agent_name or row.display_name
        if name and name not in names:
            names.append(name)
    return tuple(names)


def _candidate_from_agent(
    agent: Agent,
    name: str,
    all_agents: Sequence[Agent],
    *,
    kind: Literal["agent", "family", "clan", "tribe"] = "agent",
    member_count: int | None = None,
    aggregate_status: str | None = None,
    member_names: tuple[str, ...] = (),
) -> AgentCompletionCandidate:
    role = agent.agent_family_role or agent.role_suffix
    raw_prompt = _raw_prompt_for_agent(agent, all_agents)
    canonical_snippet = prompt_snippet(raw_prompt, humanize=False)
    return AgentCompletionCandidate(
        name=name,
        label=agent.agent_name or agent.display_name or agent.cl_name or name,
        status=agent.status,
        kind=kind,
        member_count=member_count,
        aggregate_status=aggregate_status,
        member_names=member_names,
        runtime=agent.duration_display,
        model=_model_label(agent),
        start_time=agent.start_time_short,
        duration=agent.duration_display,
        role=role,
        tag=f"@{agent.tag}" if agent.tag else None,
        vcs_workflow=vcs_workflow_from_prompt(raw_prompt),
        prompt_snippet=prompt_snippet(raw_prompt),
        search_aliases=tuple(
            alias
            for alias in (
                canonical_snippet,
                raw_vcs_tag_for_prompt(raw_prompt),
            )
            if alias
        ),
    )


def _model_label(agent: Agent) -> str | None:
    bits: list[str] = []
    if agent.llm_provider:
        bits.append(agent.llm_provider)
    if agent.model:
        bits.append(agent.model)
    label = " / ".join(bits) if bits else None
    if agent.reasoning_effort:
        return f"{label or ''}@{agent.reasoning_effort}".lstrip("@")
    return label


def _raw_prompt_for_agent(agent: Agent, all_agents: Sequence[Agent]) -> str:
    raw_content = agent.get_raw_xprompt_content() or ""
    if raw_content or not agent.parent_timestamp:
        return raw_content
    for parent in all_agents:
        if parent.raw_suffix == agent.parent_timestamp:
            return parent.get_raw_xprompt_content() or ""
    return ""


__all__ = [
    "agent_prompt_name",
    "build_agent_completion_candidates",
    "filter_agent_completion_candidates",
    "visible_clan_completion_groups",
]
