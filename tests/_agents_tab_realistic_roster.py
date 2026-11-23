"""Representative ~1,000-row agent roster fixture for delta-ownership work.

Builds a deterministic mixed roster with session containers and weak
backreferences, workflow children, clan generations, running and queued
members, capacity aliases, and ordinary current-view settings, plus 1-, 6-,
and 8-row scalar updates. Record shapes mirror the loader's real rows
(synthetic names only: no private prompts, secrets, or file contents).

The affected-closure primitive owns the write set for the scalar updates;
the production fast path stays disabled until the delta-integration phase,
so this fixture is consumed through the existing full prep pipeline plus
the new closure/ownership helpers.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

from sase.ace.tui.models.agent import Agent, AgentType

from tests._agents_tab_graph_isolation_helpers import normalize_agent_graph
from tests._agents_tab_query_helpers import make_agent

_BASE = datetime(2026, 9, 18, 9, 0, 0)
_PROJECT = "/tmp/projects/synthetic/synthetic.sase"

_ORDINARY_COUNT = 880
_SESSION_FAMILIES = 12
_WORKFLOW_STEP_FAMILIES = 6
_CLANS = ("red", "blue", "green")
_CLAN_GENERATIONS = ("g1", "g2")
_CLAN_MEMBERS_PER_GENERATION = 12
_RUNNING_COUNT = 24
_QUEUED_COUNT = 12


def _suffix(day_offset: int, hour: int, minute: int, second: int) -> str:
    moment = _BASE + timedelta(days=day_offset)
    return f"{moment:%Y%m%d}{hour:02d}{minute:02d}{second:02d}"


def realistic_roster(*, ordinary_count: int = _ORDINARY_COUNT) -> list[Agent]:
    """Build the deterministic representative roster (~1,000 rows)."""
    agents: list[Agent] = []
    for index in range(ordinary_count):
        agents.append(
            make_agent(
                cl_name=f"ordinary-{index:04d}",
                raw_suffix=_suffix(0, 9, (index // 60) % 60, index % 60),
                status="DONE",
                llm_provider="claude" if index % 2 else "codex",
                start_time=_BASE + timedelta(seconds=index),
                project_file=_PROJECT,
                fleet_origin_alias="local",
                tribe="ordinary",
            )
        )

    for family in range(_SESSION_FAMILIES):
        session = f"fam-{family:02d}"
        root_suffix = _suffix(1, 8, family, 0)
        root = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name=f"{session}-root",
            raw_suffix=root_suffix,
            status="RUNNING" if family % 3 else "DONE",
            llm_provider="claude",
            agent_name=session,
            agent_session=session,
            agent_session_role="root",
            plan_chain_root=True,
            role_suffix="--plan",
            workflow="ace(run)",
            start_time=_BASE + timedelta(days=1, minutes=family),
            run_start_time=_BASE + timedelta(days=1, minutes=family),
            project_file=_PROJECT,
            fleet_origin_alias="local",
            tribe="sessions",
        )
        members: list[Agent] = []
        for role_index, role in enumerate(("code", "review", "test")):
            queued_member = family == 0 and role == "test"
            member = make_agent(
                cl_name=f"{session}-{role}",
                raw_suffix=_suffix(1, 8, family, role_index + 1),
                status=(
                    "QUEUED"
                    if queued_member
                    else ("RUNNING" if family % 2 == 0 and role == "code" else "DONE")
                ),
                waiting_for=[f"{session}-root"] if queued_member else [],
                llm_provider="codex" if role_index % 2 else "claude",
                parent_timestamp=root_suffix,
                agent_name=f"{session}-{role}",
                agent_session=session,
                agent_session_role=role,
                role_suffix=f"--{role}",
                start_time=_BASE
                + timedelta(days=1, minutes=family, seconds=role_index + 1),
                run_start_time=_BASE
                + timedelta(days=1, minutes=family, seconds=role_index + 1),
                project_file=_PROJECT,
                fleet_origin_alias="local",
                tribe="sessions",
            )
            member.agent_session_container = root
            members.append(member)
        root.followup_agents = list(members)
        root.runtime_children = list(members)
        root.retry_chain_siblings = [members[0]]
        agents.append(root)
        agents.extend(members)
        if family < _WORKFLOW_STEP_FAMILIES:
            for step in range(2):
                agents.append(
                    make_agent(
                        cl_name=f"{session}-step-{step}",
                        raw_suffix=_suffix(1, 10, family, step),
                        status="DONE",
                        llm_provider="claude",
                        parent_workflow="ace(run)",
                        parent_timestamp=root_suffix,
                        parent_step_index=step,
                        step_index=step,
                        step_type="tool",
                        step_name=f"step-{step}",
                        is_hidden_step=False,
                        agent_session=session,
                        agent_session_role="code",
                        start_time=_BASE + timedelta(days=1, hours=2, minutes=family),
                        project_file=_PROJECT,
                        fleet_origin_alias="local",
                        tribe="sessions",
                    )
                )

    for clan in _CLANS:
        for generation in _CLAN_GENERATIONS:
            container = make_agent(
                cl_name=f"clan-{clan}-{generation}",
                raw_suffix=None,
                is_clan_container=True,
                agent_clan=f"clan-{clan}",
                agent_clan_generation=generation,
                start_time=_BASE,
                project_file=_PROJECT,
                fleet_origin_alias="local",
                tribe=f"clan-{clan}",
            )
            members = [
                make_agent(
                    cl_name=f"clan-{clan}-{generation}-{index:02d}",
                    raw_suffix=_suffix(2, 9, index, len(clan)),
                    status="RUNNING" if index < 2 else "DONE",
                    llm_provider="codex" if index % 2 else "claude",
                    agent_clan=f"clan-{clan}",
                    agent_clan_generation=generation,
                    tribe=f"clan-{clan}",
                    start_time=_BASE + timedelta(days=2, minutes=index),
                    run_start_time=_BASE + timedelta(days=2, minutes=index),
                    project_file=_PROJECT,
                    fleet_origin_alias="local",
                )
                for index in range(_CLAN_MEMBERS_PER_GENERATION)
            ]
            container.runtime_children = list(members)
            agents.append(container)
            agents.extend(members)

    for index in range(_RUNNING_COUNT):
        agents.append(
            make_agent(
                cl_name=f"running-{index:03d}",
                raw_suffix=_suffix(3, 7, index, 0),
                status="RUNNING",
                llm_provider="claude" if index % 2 else "codex",
                runner_is_live=True,
                pid=20000 + index,
                start_time=_BASE + timedelta(days=3, minutes=index),
                run_start_time=_BASE + timedelta(days=3, minutes=index),
                project_file=_PROJECT,
                fleet_origin_alias="local" if index % 6 else "remote-athena",
                tribe="running",
            )
        )
    for index in range(_QUEUED_COUNT):
        agents.append(
            make_agent(
                cl_name=f"queued-{index:03d}",
                raw_suffix=_suffix(3, 8, index, 0),
                status="QUEUED",
                llm_provider="codex",
                waiting_for=[f"ordinary-{index:04d}"],
                runner_slot_queue_position=index,
                start_time=_BASE + timedelta(days=3, hours=1, minutes=index),
                project_file=_PROJECT,
                fleet_origin_alias="local",
                tribe="running",
            )
        )
    return normalize_agent_graph(agents)


def scalar_deltas(live: list[Agent], count: int) -> list[Agent]:
    """Return *count* scalar-only incoming rows (deep copies, status only)."""
    assert count in (1, 6, 8)
    ordinary = [agent for agent in live if agent.cl_name.startswith("ordinary-")]
    # Session display statuses are rewritten by status overrides during
    # normalization (``WORKING PLAN``/``PLAN DONE`` instead of ``RUNNING``),
    # so select by role and transition to a terminal status. ``status`` is
    # not a relationship key, so the change stays scalar.
    # Family 0 carries the queued waiter, so its code member exercises
    # session, wait-source, and capacity effects in the single-row case.
    session_code = next(agent for agent in live if agent.cl_name == "fam-00-code")
    if count == 1:
        targets = [session_code]
    else:
        targets = [session_code, *ordinary[: count - 1]]
    incoming: list[Agent] = []
    for agent in targets:
        clone = deepcopy(agent)
        clone.status = "DONE" if agent is session_code else "FAILED"
        incoming.append(clone)
    return incoming


def ordinary_counts(live: list[Agent]) -> dict[str, int]:
    """Count fixture rows by kind for shape assertions."""
    return {
        "total": len(live),
        "ordinary": sum(1 for agent in live if agent.cl_name.startswith("ordinary-")),
        "session_rows": sum(1 for agent in live if agent.agent_session),
        "workflow_steps": sum(1 for agent in live if agent.parent_workflow),
        "clan_rows": sum(1 for agent in live if agent.agent_clan),
        "clan_containers": sum(1 for agent in live if agent.is_clan_container),
        "running": sum(1 for agent in live if agent.status == "RUNNING"),
        "queued": sum(1 for agent in live if agent.status == "QUEUED"),
        "remote_alias": sum(
            1 for agent in live if agent.fleet_origin_alias == "remote-athena"
        ),
    }
