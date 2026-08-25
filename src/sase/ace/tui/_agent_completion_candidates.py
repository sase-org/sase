"""Construction and filtering of visible-agent completion candidates."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sase.agent_family_plan_preview import AgentFamilyPlanPreview
from sase.ace.tui._agent_completion_models import AgentCompletionCandidate
from sase.ace.tui._agent_completion_prompt import (
    prompt_snippet,
    raw_vcs_tag_for_prompt,
    vcs_workflow_from_prompt,
)
from sase.ace.tui.models.agent_family_preview_cache import (
    FAMILY_PREVIEW_CACHE_MISS,
    cached_family_plan_preview,
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
    tribes: tuple[str, ...]


def agent_prompt_name(agent: Agent) -> str | None:
    """Return the prompt-referenceable name for an agent row."""
    return agent.presented_agent_name or agent.agent_name


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
    procs = _build_proc_completion_candidates(
        all_agents,
        exclude_identity=exclude_identity,
    )
    tribes = _build_tribe_completion_candidates(all_agents, clan_groups)
    return _dedupe_completion_candidates([*tribes, *clans, *families, *agents, *procs])


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
            or agent.is_proc_shell
            or agent.is_monitor
            or (exclude_identity is not None and agent.identity == exclude_identity)
        ):
            continue
        name = agent_prompt_name(agent)
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        candidates.append(_candidate_from_agent(agent, name, all_agents))
    return candidates


def _build_proc_completion_candidates(
    all_agents: Sequence[Agent],
    *,
    exclude_identity: object | None,
) -> list[AgentCompletionCandidate]:
    """Return stand-alone proc-shell and monitor rows as ``proc``-kind candidates.

    The insertion reference is the exact durable proc ID (never the reusable
    friendly shell name) so ``#fork``/``%wait`` completion can never drift
    onto a different proc if the name is reused later.
    """
    from sase.procs import short_proc_id

    candidates: list[AgentCompletionCandidate] = []
    seen_ids: set[str] = set()
    for agent in all_agents:
        if not (agent.is_proc_shell or agent.is_monitor):
            continue
        if exclude_identity is not None and agent.identity == exclude_identity:
            continue
        proc_id = agent.proc_id if agent.is_proc_shell else agent.monitor_id
        if not proc_id or proc_id in seen_ids:
            continue
        seen_ids.add(proc_id)
        shell_name = agent_prompt_name(agent) or short_proc_id(proc_id)
        preview = agent.proc_safe_preview or agent.monitor_command or ""
        candidates.append(
            AgentCompletionCandidate(
                name=proc_id,
                label=shell_name,
                status=agent.status,
                kind="proc",
                proc_id=proc_id,
                runtime=agent.duration_display,
                start_time=agent.start_time_short,
                duration=agent.duration_display,
                role="monitor" if agent.is_monitor else "proc",
                prompt_snippet=prompt_snippet(preview, humanize=False),
                search_aliases=tuple(
                    dict.fromkeys(
                        alias
                        for alias in (shell_name, short_proc_id(proc_id))
                        if alias and alias != proc_id
                    )
                ),
            )
        )
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
    values = (candidate.name, *candidate.search_aliases)
    if candidate.kind != "tribe" or partial_lower.startswith("@"):
        return any(value.lower().startswith(partial_lower) for value in values)
    return any(
        value.removeprefix("@").lower().startswith(partial_lower) for value in values
    )


def visible_clan_completion_groups(
    all_agents: Sequence[Agent],
) -> list[_ClanCompletionGroup]:
    """Return each clan's newest visible generation in stable display order."""
    rows_by_key: dict[tuple[str, str | None], list[tuple[int, Agent]]] = {}
    for index, agent in enumerate(all_agents):
        if not agent.agent_clan:
            continue
        key = (_presented_clan_name(agent), agent.agent_clan_generation)
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
                tribes=_clan_group_tribes(container, rows),
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


def _presented_clan_name(agent: Agent) -> str:
    """Derive a clan's presentation from already-normalized row identity."""
    return agent.presented_clan_reference_name() or ""


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


def _clan_group_tribes(
    container: Agent | None,
    rows: Sequence[Agent],
) -> tuple[str, ...]:
    tribes: list[str] = []
    if container is not None:
        tribes.extend(container.clan_tribes)
        if container.clan_tribe:
            tribes.append(container.clan_tribe)
        if container.tribe:
            tribes.append(container.tribe)
    if not tribes:
        tribes.extend(row.clan_tribe or row.tribe or "" for row in rows)
    return tuple(dict.fromkeys(tribe for tribe in tribes if tribe))


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
                search_aliases=tuple(
                    dict.fromkeys(
                        raw
                        for member in group.members
                        if (raw := member.agent_clan) and raw != group.name
                    )
                ),
            )
        )
    return candidates


def _build_family_completion_candidates(
    all_agents: Sequence[Agent],
    *,
    exclude_identity: object | None,
) -> list[AgentCompletionCandidate]:
    from sase.ace.tui.models.agent_family_members import concrete_family_shell_rows

    candidates: list[AgentCompletionCandidate] = []
    seen_names: set[str] = set()
    for agent in all_agents:
        if not agent.is_family_root_entry or agent.is_clan_container:
            continue
        name = agent_prompt_name(agent)
        if not name or name in seen_names:
            continue
        members = _dedupe_real_member_rows(concrete_family_shell_rows(agent))
        if not members or (
            exclude_identity is not None
            and any(member.identity == exclude_identity for member in members)
        ):
            continue
        seen_names.add(name)
        status = _aggregate_completion_status(members)
        plan_preview = _cached_plan_preview_for_family(agent)
        preview_aliases = (
            (plan_preview.title,)
            if plan_preview is not None and plan_preview.title
            else ()
        )
        candidates.append(
            _candidate_from_agent(
                agent,
                name,
                all_agents,
                kind="family",
                member_count=len(members),
                aggregate_status=status,
                member_names=_member_names(members),
                plan_preview=plan_preview,
                extra_search_aliases=preview_aliases,
            )
        )
    return candidates


def _cached_plan_preview_for_family(
    agent: Agent,
) -> AgentFamilyPlanPreview | None:
    cached = cached_family_plan_preview(agent)
    if cached is FAMILY_PREVIEW_CACHE_MISS or cached is None:
        return None
    assert isinstance(cached, AgentFamilyPlanPreview)
    return cached


def _build_tribe_completion_candidates(
    all_agents: Sequence[Agent],
    clan_groups: Sequence[_ClanCompletionGroup],
) -> list[AgentCompletionCandidate]:
    """Build canonical ``@tribe`` targets from already-loaded rows and clans."""
    from sase.ace.tui.models.agent_family_members import concrete_family_shell_rows

    clan_group_by_key = {(group.name, group.generation): group for group in clan_groups}
    encountered_clans: set[tuple[str, str | None]] = set()
    members_by_tribe: dict[str, list[Agent]] = {}
    agent_carriers_by_tribe: dict[str, set[object]] = {}
    clan_carriers_by_tribe: dict[str, set[tuple[str, str | None]]] = {}
    tribe_order: list[str] = []

    def add(
        tribe: str,
        members: Iterable[Agent],
        *,
        agent_carrier: object | None = None,
        clan_carrier: tuple[str, str | None] | None = None,
    ) -> None:
        bare_tribe = tribe.removeprefix("@")
        if not bare_tribe:
            return
        if bare_tribe not in members_by_tribe:
            members_by_tribe[bare_tribe] = []
            agent_carriers_by_tribe[bare_tribe] = set()
            clan_carriers_by_tribe[bare_tribe] = set()
            tribe_order.append(bare_tribe)
        members_by_tribe[bare_tribe].extend(members)
        if agent_carrier is not None:
            agent_carriers_by_tribe[bare_tribe].add(agent_carrier)
        if clan_carrier is not None:
            clan_carriers_by_tribe[bare_tribe].add(clan_carrier)

    for agent in all_agents:
        if agent.agent_clan:
            key = (_presented_clan_name(agent), agent.agent_clan_generation)
            group = clan_group_by_key.get(key)
            if group is None or key in encountered_clans:
                continue
            encountered_clans.add(key)
            for tribe in group.tribes:
                add(tribe, group.members, clan_carrier=key)
            continue
        if agent.is_clan_container or agent.is_synthetic_planner or not agent.tribe:
            continue
        members: Iterable[Agent]
        if agent.is_family_root_entry:
            members = concrete_family_shell_rows(agent)
        else:
            members = (agent,)
        add(agent.tribe, members, agent_carrier=agent.identity)

    candidates: list[AgentCompletionCandidate] = []
    for tribe in tribe_order:
        members = _dedupe_real_member_rows(members_by_tribe[tribe])
        if not members:
            continue
        status = _aggregate_completion_status(members)
        candidates.append(
            AgentCompletionCandidate(
                name=f"@{tribe}",
                label=tribe,
                status=status,
                kind="tribe",
                member_count=len(members),
                aggregate_status=status,
                member_names=_member_names(members),
                agent_count=len(agent_carriers_by_tribe[tribe]),
                clan_count=len(clan_carriers_by_tribe[tribe]),
                search_aliases=(tribe,),
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
        name = row.presented_agent_name or row.agent_name or row.display_name
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
    plan_preview: AgentFamilyPlanPreview | None = None,
    extra_search_aliases: tuple[str, ...] = (),
) -> AgentCompletionCandidate:
    role = agent.agent_family_role or agent.role_suffix
    raw_prompt = _raw_prompt_for_agent(agent, all_agents)
    canonical_snippet = prompt_snippet(raw_prompt, humanize=False)
    return AgentCompletionCandidate(
        name=name,
        label=_completion_label(agent, name),
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
        tribe=f"@{agent.tribe}" if agent.tribe else None,
        vcs_workflow=vcs_workflow_from_prompt(raw_prompt),
        plan_preview=plan_preview,
        prompt_snippet=prompt_snippet(raw_prompt),
        search_aliases=tuple(
            alias
            for alias in (
                agent.agent_name if agent.agent_name != name else None,
                agent.agent_family if agent.agent_family != name else None,
                canonical_snippet,
                raw_vcs_tag_for_prompt(raw_prompt),
                *extra_search_aliases,
            )
            if alias
        ),
    )


def _completion_label(agent: Agent, fallback: str) -> str:
    """Return the concrete row label while keeping the local hood hidden."""
    presented = agent.presented_agent_name
    raw_name = agent.agent_name
    raw_family = agent.agent_family
    if (
        agent.is_family_root_entry
        and presented
        and raw_name
        and raw_family
        and raw_name.startswith(raw_family)
    ):
        return presented + raw_name[len(raw_family) :]
    return presented or agent.display_name or agent.cl_name or fallback


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
    if not raw_content and agent.is_family_root_entry:
        from sase.ace.tui.models.agent_family_members import concrete_family_member_rows

        for member in concrete_family_member_rows(agent):
            if member is agent:
                continue
            raw_content = member.get_raw_xprompt_content() or ""
            if raw_content:
                return raw_content
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
