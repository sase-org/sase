"""Tests for the visible-agent completion roster."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.css.query import NoMatches

from sase.ace.tui.actions.agents._display_helpers import panel_widget_id
from sase.ace.tui.agent_completion import (
    build_agent_completion_candidates,
    visible_agent_completion_agents,
)
from sase.ace.tui.models import filter_agents_by_fold_state
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.fold_state import FoldLevel, FoldStateManager
from sase.core.time import local_now


class _FakeAgentList:
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents

    def visible_agents(self) -> list[Agent]:
        return self._agents


class _CompletionApp:
    def __init__(
        self,
        agents: list[Agent],
        panel_rows: dict[int, list[Agent]] | None,
    ) -> None:
        self._agents = agents
        self._panel_group = AgentPanelGroup.from_agents(agents)
        self._panel_rows = panel_rows

    def query_one(self, selector: str, _widget_type: object) -> _FakeAgentList:
        if self._panel_rows is None:
            raise NoMatches(selector)
        for panel_idx, agents in self._panel_rows.items():
            if selector == f"#{panel_widget_id(panel_idx)}":
                return _FakeAgentList(agents)
        raise NoMatches(selector)


def _agent(tmp_path: Path, **overrides: Any) -> Agent:
    defaults: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "sase",
        "project_file": "/tmp/projects/sase/sase.sase",
        "status": "RUNNING",
        "start_time": local_now(),
        "raw_suffix": "260624_120000",
        "agent_name": "coder",
    }
    defaults.update(overrides)
    return Agent(**defaults)


def test_visible_agent_completion_agents_aggregates_all_panel_widgets(
    tmp_path: Path,
) -> None:
    no_tribe = _agent(tmp_path, agent_name="no-tribe", raw_suffix="260624_120020")
    alpha = _agent(
        tmp_path,
        agent_name="alpha",
        raw_suffix="260624_120021",
        tribe="alpha",
    )
    alpha_extra = _agent(
        tmp_path,
        agent_name="alpha-extra",
        raw_suffix="260624_120022",
        tribe="alpha",
    )
    beta = _agent(
        tmp_path,
        agent_name="beta",
        raw_suffix="260624_120023",
        tribe="beta",
    )
    app = _CompletionApp(
        [no_tribe, alpha, alpha_extra, beta],
        {
            0: [no_tribe],
            1: [alpha, alpha_extra],
            2: [beta, alpha],
        },
    )
    app._panel_group.focused_idx = 1

    assert visible_agent_completion_agents(app) == [
        no_tribe,
        alpha,
        alpha_extra,
        beta,
    ]


def test_visible_agent_completion_agents_falls_back_when_no_widgets(
    tmp_path: Path,
) -> None:
    first = _agent(tmp_path, agent_name="first", raw_suffix="260624_120030")
    hidden_starting = _agent(
        tmp_path,
        agent_name="starting",
        raw_suffix="260624_120031",
        status="STARTING",
    )
    second = _agent(tmp_path, agent_name="second", raw_suffix="260624_120032")
    app = _CompletionApp([first, hidden_starting, second], None)

    assert visible_agent_completion_agents(app) == [first, second]


def test_visible_agent_completion_agents_uses_visible_order_fallback(
    tmp_path: Path,
) -> None:
    first = _agent(tmp_path, agent_name="first", raw_suffix="260624_120040")
    second = _agent(tmp_path, agent_name="second", raw_suffix="260624_120041")

    class _FallbackOrderApp(_CompletionApp):
        def _agents_visible_order(self) -> list[int]:
            return [1, 99, 0]

    app = _FallbackOrderApp([first, second], None)

    assert visible_agent_completion_agents(app) == [second, first]


def test_visible_agent_completion_agents_adds_collapsed_clan_lanes(
    tmp_path: Path,
) -> None:
    standalone = _agent(
        tmp_path,
        agent_name="crew.solo",
        raw_suffix="260624_120050",
        cl_name="",
        agent_clan="crew",
        agent_clan_generation="generation",
    )
    family = _agent(
        tmp_path,
        agent_name="crew.family--plan",
        raw_suffix="260624_120051",
        cl_name="",
        agent_clan="crew",
        agent_clan_generation="generation",
        agent_family="crew.family",
        agent_family_role="root",
        plan_chain_root=True,
    )
    family_member = _agent(
        tmp_path,
        agent_name="crew.family--code",
        raw_suffix="260624_120052",
        cl_name="",
        agent_family="crew.family",
        agent_family_role="code",
        parent_timestamp=family.raw_suffix,
    )
    family.followup_agents.append(family_member)
    unrelated = _agent(
        tmp_path,
        agent_name="unrelated",
        raw_suffix="260624_120053",
        cl_name="",
    )
    complete = project_clan_tree([standalone, family, family_member, unrelated])
    fold_manager = FoldStateManager()
    rendered, _fold_counts = filter_agents_by_fold_state(complete, fold_manager)
    clan = next(agent for agent in complete if agent.is_clan_container)
    clan_fold_key = agent_fold_key(clan)
    assert clan_fold_key is not None
    assert family.raw_suffix is not None
    app = _CompletionApp(rendered, None)
    app._agents_with_children = complete
    app._fold_manager = fold_manager

    roster = visible_agent_completion_agents(app)

    assert roster == [clan, standalone, family, unrelated]
    assert fold_manager.get(clan_fold_key) is FoldLevel.COLLAPSED
    assert fold_manager.get(family.raw_suffix) is FoldLevel.COLLAPSED
    candidates = build_agent_completion_candidates(roster)
    clan_candidates = [
        candidate
        for candidate in candidates
        if candidate.kind == "clan" and candidate.name == "crew"
    ]
    assert len(clan_candidates) == 1
    assert (
        next(
            candidate for candidate in candidates if candidate.name == "crew.solo"
        ).kind
        == "agent"
    )
    family_candidate = next(
        candidate for candidate in candidates if candidate.name == "crew.family"
    )
    assert family_candidate.kind == "family"
    assert family_candidate.member_count == 2
    assert all(candidate.name != "crew.family--code" for candidate in candidates)


def test_visible_agent_completion_agents_deduplicates_expanded_clan(
    tmp_path: Path,
) -> None:
    first = _agent(
        tmp_path,
        agent_name="crew.first",
        raw_suffix="260624_120060",
        cl_name="",
        agent_clan="crew",
        agent_clan_generation="generation",
    )
    second = _agent(
        tmp_path,
        agent_name="crew.second",
        raw_suffix="260624_120061",
        cl_name="",
        agent_clan="crew",
        agent_clan_generation="generation",
    )
    complete = project_clan_tree([first, second])
    clan = next(agent for agent in complete if agent.is_clan_container)
    clan_fold_key = agent_fold_key(clan)
    assert clan_fold_key is not None
    fold_manager = FoldStateManager()
    fold_manager.expand(clan_fold_key)
    rendered, _fold_counts = filter_agents_by_fold_state(complete, fold_manager)
    app = _CompletionApp(rendered, {0: [*rendered, first]})
    app._agents_with_children = complete
    app._fold_manager = fold_manager

    roster = visible_agent_completion_agents(app)

    assert roster == rendered
    assert len({agent.identity for agent in roster}) == len(roster)


def test_visible_agent_completion_agents_preserves_non_clan_visibility(
    tmp_path: Path,
) -> None:
    visible = _agent(
        tmp_path,
        agent_name="eligible.visible",
        raw_suffix="260624_120070",
        agent_clan="crew",
        agent_clan_generation="generation",
    )
    filtered = _agent(
        tmp_path,
        agent_name="outside.filtered",
        raw_suffix="260624_120071",
        agent_clan="other",
        agent_clan_generation="generation",
    )
    starting = _agent(
        tmp_path,
        agent_name="eligible.starting",
        raw_suffix="260624_120072",
        status="STARTING",
        agent_clan="crew",
        agent_clan_generation="generation",
    )
    dismissed = _agent(
        tmp_path,
        agent_name="eligible.dismissed",
        raw_suffix="260624_120073",
        agent_clan="crew",
        agent_clan_generation="generation",
    )
    complete = project_clan_tree([visible, filtered, starting, dismissed])
    clan = next(
        agent
        for agent in complete
        if agent.is_clan_container and agent.agent_clan == "crew"
    )
    app = _CompletionApp([clan], None)
    app._agents_with_children = complete
    app._fold_manager = FoldStateManager()
    app._agent_search_query = "name:eligible"
    app._dismissed_agents = {dismissed.identity}

    assert visible_agent_completion_agents(app) == [clan, visible]
