"""Per-agent stranded-work row projection from warm report snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.agent.bead_display import derive_agent_bead_id_from_name

from ._agent_stranded_cache import stranded_project_key_for_agent, stranded_report_cache

if TYPE_CHECKING:
    from sase.core.stranded_work_facade import StrandedWorkVerdict

    from .agent import Agent


@dataclass(frozen=True, slots=True)
class _AgentStrandedView:
    """Cached stranded state that can affect one rendered agent row."""

    verdict: StrandedWorkVerdict | None = None
    waiting_on: tuple[tuple[str, str], ...] = ()
    waiting_on_agents: tuple[tuple[str, str], ...] = ()
    clan_stranded_ids: tuple[str, ...] = ()
    clan_stranded_member_keys: tuple[str, ...] = ()
    clan_leaf_direct: bool = False
    wait_project: str | None = None
    clan_project: str | None = None

    @property
    def signature(self) -> tuple[object, ...]:
        """Return the immutable presentation inputs for row-render caching."""
        verdict = self.verdict
        return (
            None
            if verdict is None
            else (
                verdict.bead_id,
                verdict.state,
                verdict.reason,
                verdict.blocked_by,
            ),
            self.waiting_on,
            self.waiting_on_agents,
            self.clan_stranded_ids,
            self.clan_stranded_member_keys,
            self.clan_leaf_direct,
        )


def _agent_bead_id_for_stranded(agent: Agent) -> str | None:
    """Return the bead candidate attached to a real Agents-tab agent node."""
    from .agent_nodes import is_agents_tab_agent_node

    if not is_agents_tab_agent_node(agent):
        return None
    phase_bead_id = getattr(agent, "phase_bead_id", None)
    if isinstance(phase_bead_id, str) and phase_bead_id.strip():
        return phase_bead_id.strip()
    return derive_agent_bead_id_from_name(
        getattr(agent, "presented_agent_name", None)
        or getattr(agent, "agent_name", None)
    )


def verdict_index_for_project(
    project_key: str | None,
) -> dict[str, StrandedWorkVerdict]:
    if project_key is None:
        return {}
    return stranded_report_cache().verdict_index(project_key) or {}


def _stranded_verdict_for_agent(agent: Agent) -> StrandedWorkVerdict | None:
    """Return the cached verdict for the bead attached to *agent*, if any."""
    bead_id = _agent_bead_id_for_stranded(agent)
    if bead_id is None:
        return None
    return verdict_index_for_project(stranded_project_key_for_agent(agent)).get(bead_id)


def stranded_leaf_verdict(agent: Agent) -> StrandedWorkVerdict | None:
    """Return the cached stranded verdict for a real agent row."""
    verdict = _stranded_verdict_for_agent(agent)
    return verdict if verdict is not None and verdict.state == "stranded" else None


def _clan_wave_member_key(agent: Agent) -> str:
    return (
        f"{agent.agent_type.value}:{agent.cl_name}:"
        f"{agent.raw_suffix or ''}:{agent.agent_name or ''}"
    )


def _clan_epic_id(agent: Agent) -> str | None:
    """Return the epic bead ID a clan container is named after."""
    clan = getattr(agent, "agent_clan", None)
    if isinstance(clan, str) and clan.strip():
        return clan.strip()
    name = getattr(agent, "presented_agent_name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _flagged_wait_target(
    bead_id: str | None, verdicts: dict[str, StrandedWorkVerdict]
) -> tuple[str, str] | None:
    if not bead_id:
        return None
    target = verdicts.get(bead_id)
    if target is None or target.state not in {"stranded", "blocked"}:
        return None
    return (target.bead_id, target.state)


def agent_stranded_view(agent: Agent) -> _AgentStrandedView:
    """Build row overlays from warm reports without filesystem access."""
    from .agent_time import wait_display_agent

    verdict = _stranded_verdict_for_agent(agent)
    wait_agent = wait_display_agent(agent)
    waiting_on: list[tuple[str, str]] = []
    waiting_on_agents: list[tuple[str, str]] = []
    wait_project = stranded_project_key_for_agent(
        wait_agent
    ) or stranded_project_key_for_agent(agent)
    wait_verdicts = verdict_index_for_project(wait_project)
    for bead_id in getattr(wait_agent, "waiting_for_beads", ()):
        flagged = _flagged_wait_target(bead_id, wait_verdicts)
        if flagged is not None:
            waiting_on.append(flagged)
    for name in getattr(wait_agent, "waiting_for", ()):
        flagged = _flagged_wait_target(
            derive_agent_bead_id_from_name(name), wait_verdicts
        )
        if flagged is not None:
            waiting_on_agents.append(flagged)

    clan_stranded: set[str] = set()
    clan_member_keys: set[str] = set()
    clan_leaf_direct = False
    clan_project: str | None = None
    if getattr(agent, "is_clan_container", False):
        from ._agent_clan import clan_members

        members = clan_members(agent)
        project_key = stranded_project_key_for_agent(agent)
        if project_key is None:
            for member in members:
                project_key = stranded_project_key_for_agent(member)
                if project_key is not None:
                    break
        clan_project = project_key
        verdicts = verdict_index_for_project(project_key)
        epic_id = _clan_epic_id(agent)
        epic_verdict = verdicts.get(epic_id) if epic_id else None
        if epic_verdict is not None:
            if epic_verdict.state == "stranded":
                clan_stranded.add(epic_verdict.bead_id)
            clan_stranded.update(epic_verdict.blocked_by)
        for member in members:
            member_bead_id = _agent_bead_id_for_stranded(member)
            member_verdict = verdict_index_for_project(
                stranded_project_key_for_agent(member)
            ).get(member_bead_id or "")
            if member_verdict is None:
                continue
            if member_verdict.state == "stranded":
                clan_stranded.add(member_verdict.bead_id)
            if member_verdict.state in {"stranded", "blocked"}:
                clan_member_keys.add(_clan_wave_member_key(member))
        if epic_verdict is not None and epic_verdict.state == "stranded":
            clan_leaf_direct = True
        elif epic_id:
            clan_leaf_direct = any(
                (leaf := verdicts.get(leaf_id)) is not None
                and leaf.parent_id == epic_id
                for leaf_id in clan_stranded
            )

    return _AgentStrandedView(
        verdict=verdict,
        waiting_on=tuple(sorted(waiting_on)),
        waiting_on_agents=tuple(sorted(waiting_on_agents)),
        clan_stranded_ids=tuple(sorted(clan_stranded)),
        clan_stranded_member_keys=tuple(sorted(clan_member_keys)),
        clan_leaf_direct=clan_leaf_direct,
        wait_project=wait_project,
        clan_project=clan_project,
    )
