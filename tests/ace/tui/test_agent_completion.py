"""Tests for shared visible-agent completion candidates."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.style import Style
from textual.css.query import NoMatches

from sase.ace.tui.actions.agents._display_helpers import panel_widget_id
from sase.ace.tui.agent_completion import (
    build_agent_completion_candidates,
    filter_agent_completion_candidates,
    status_style,
    visible_agent_completion_agents,
)
from sase.ace.tui.models import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.fold_state import FoldLevel, FoldStateManager
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)


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
    raw_prompt = overrides.pop("raw_prompt", None)
    artifacts_dir = overrides.pop("artifacts_dir", None)
    if raw_prompt is not None:
        artifact_root = tmp_path / str(overrides.get("raw_suffix", "agent"))
        artifact_root.mkdir()
        (artifact_root / "raw_xprompt.md").write_text(raw_prompt, encoding="utf-8")
        artifacts_dir = str(artifact_root)

    defaults: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "sase",
        "project_file": "/tmp/projects/sase/sase.sase",
        "status": "RUNNING",
        "start_time": datetime(2026, 6, 24, 12, 0, 0),
        "raw_suffix": "260624_120000",
        "agent_name": "coder",
        "artifacts_dir": artifacts_dir,
    }
    defaults.update(overrides)
    return Agent(**defaults)


def test_build_agent_completion_candidates_enriches_visible_named_agents(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "sase.xprompt.extract_vcs_workflow_tag",
        lambda prompt: "#gh:sase " if prompt.startswith("#gh:sase ") else None,
    )
    monkeypatch.setattr(
        "sase.xprompt.strip_vcs_workflow_tag",
        lambda prompt: prompt.removeprefix("#gh:sase "),
    )
    monkeypatch.setattr(
        "sase.xprompt.extract_project_from_vcs_tag",
        lambda tag: "sase" if tag.strip() == "#gh:sase" else None,
    )
    monkeypatch.setattr(
        "sase.workspace_provider.get_display_name",
        lambda workflow_type: "GitHub" if workflow_type == "gh" else None,
    )

    family = _agent(
        tmp_path,
        agent_name="completion.plan",
        agent_family="completion",
        agent_family_role="root",
        plan_chain_root=True,
        model="gpt-5",
        llm_provider="codex",
        reasoning_effort="high",
        tribe="review",
        raw_prompt="%wait(old, time=5m) #gh:sase Redesign wait completion\nwith rows",
    )
    duplicate = _agent(tmp_path, agent_name="completion", raw_suffix="260624_120001")
    unnamed = _agent(tmp_path, agent_name=None, raw_suffix="260624_120002")
    other = _agent(tmp_path, agent_name="verifier", raw_suffix="260624_120003")

    candidates = build_agent_completion_candidates(
        [family, duplicate, unnamed, other],
        exclude_identity=other.identity,
    )

    assert [candidate.name for candidate in candidates] == ["@review", "completion"]
    assert candidates[0].kind == "tribe"
    assert candidates[0].member_count == 1
    candidate = candidates[1]
    assert candidate.kind == "family"
    assert candidate.member_count == 1
    assert candidate.label == "completion.plan"
    assert candidate.model == "codex / gpt-5@high"
    assert candidate.tribe == "@review"
    assert candidate.prompt_snippet == "Redesign wait completion with rows"
    assert candidate.vcs_workflow is not None
    assert candidate.vcs_workflow.display == "#gh:sase"
    assert candidate.vcs_workflow.workflow_type == "gh"
    assert candidate.vcs_workflow.project == "sase"
    assert candidate.vcs_workflow.provider_display == "GitHub"


def test_build_agent_completion_candidates_humanizes_vcs_badge_and_searches_raw(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})
    monkeypatch.setattr(
        "sase.project_display_names._project_display_name_map_cached",
        lambda _projects_root=None: {"gh_acme__widgets": "widgets"},
    )
    monkeypatch.setattr(
        "sase.xprompt.extract_vcs_workflow_tag",
        lambda prompt: (
            "#gh:gh_acme__widgets "
            if prompt.startswith("#gh:gh_acme__widgets ")
            else None
        ),
    )
    monkeypatch.setattr(
        "sase.xprompt.strip_vcs_workflow_tag",
        lambda prompt: prompt.removeprefix("#gh:gh_acme__widgets "),
    )

    agent = _agent(
        tmp_path,
        agent_name="coder",
        raw_prompt=(
            "#gh:gh_acme__widgets Review #gh:gh_acme__widgets_fix_parser_1 docs"
        ),
    )

    candidates = build_agent_completion_candidates([agent])

    candidate = candidates[0]
    assert candidate.vcs_workflow is not None
    assert candidate.vcs_workflow.display == "#gh:widgets"
    assert candidate.vcs_workflow.project == "widgets"
    assert candidate.prompt_snippet == "Review #gh:widgets_fix_parser_1 docs"
    assert "gh_acme__widgets_fix_parser_1" in candidate.search_text
    assert "widgets_fix_parser_1" in candidate.search_text


def test_filter_agent_completion_candidates_uses_name_prefix(tmp_path: Path) -> None:
    candidates = build_agent_completion_candidates(
        [
            _agent(tmp_path, agent_name="planner", raw_suffix="260624_120010"),
            _agent(tmp_path, agent_name="coder", raw_suffix="260624_120011"),
        ]
    )

    assert [
        candidate.name
        for candidate in filter_agent_completion_candidates(candidates, "co")
    ] == ["coder"]


def test_completion_inserts_bare_local_names_and_searches_raw_alias(
    tmp_path: Path,
) -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    local = _agent(tmp_path, agent_name="athena.foo.plan")
    legacy = _agent(
        tmp_path,
        agent_name="bar.plan",
        raw_suffix="260624_120011",
    )
    foreign = _agent(
        tmp_path,
        agent_name="zeus.foo.plan",
        raw_suffix="260624_120012",
    )
    for agent in (local, legacy, foreign):
        agent.refresh_presented_agent_name(identity)

    candidates = build_agent_completion_candidates([local, legacy, foreign])

    assert [candidate.name for candidate in candidates] == [
        "foo.plan",
        "bar.plan",
        "zeus.foo.plan",
    ]
    assert [
        candidate.name
        for candidate in filter_agent_completion_candidates(candidates, "athena.foo")
    ] == ["foo.plan"]


def test_clan_tree_merges_legacy_and_qualified_local_metadata(
    tmp_path: Path,
) -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    legacy = _agent(
        tmp_path,
        agent_name="research.legacy",
        agent_clan="research",
        agent_clan_generation="generation",
        raw_suffix="260624_120010",
    )
    qualified = _agent(
        tmp_path,
        agent_name="athena.research.new",
        agent_clan="athena.research",
        agent_clan_generation="generation",
        raw_suffix="260624_120011",
    )
    foreign = _agent(
        tmp_path,
        agent_name="zeus.research.remote",
        agent_clan="zeus.research",
        agent_clan_generation="generation",
        raw_suffix="260624_120012",
    )
    for agent in (legacy, qualified, foreign):
        agent.refresh_presented_agent_name(identity)

    projected = project_clan_tree([legacy, qualified, foreign])
    containers = [agent for agent in projected if agent.is_clan_container]

    assert [container.agent_clan for container in containers] == [
        "research",
        "zeus.research",
    ]
    assert [len(container.runtime_children) for container in containers] == [2, 1]


def test_build_agent_completion_candidates_derives_ordered_groups(
    tmp_path: Path,
) -> None:
    old = _agent(
        tmp_path,
        agent_name="review.old",
        raw_suffix="20260718090000",
        agent_clan="review",
        agent_clan_generation="20260718090000",
        tribe="retired",
    )
    alpha = _agent(
        tmp_path,
        agent_name="review.alpha",
        raw_suffix="20260718100001",
        agent_clan="review",
        agent_clan_generation="20260718100000",
        tribe="builders",
    )
    beta = _agent(
        tmp_path,
        agent_name="review.beta",
        raw_suffix="20260718100002",
        agent_clan="review",
        agent_clan_generation="20260718100000",
        status="DONE",
    )
    family = _agent(
        tmp_path,
        agent_name="ship--plan",
        raw_suffix="20260718110000",
        agent_family="ship",
        agent_family_role="root",
        plan_chain_root=True,
        tribe="makers",
    )
    code = _agent(
        tmp_path,
        agent_name="ship--code",
        raw_suffix="20260718110001",
        agent_family="ship",
        agent_family_role="code",
        parent_timestamp=family.raw_suffix,
    )
    family.followup_agents.append(code)
    solo = _agent(
        tmp_path,
        agent_name="solo",
        raw_suffix="20260718120000",
        tribe="builders",
    )

    candidates = build_agent_completion_candidates(
        [*project_clan_tree([old, alpha, beta]), family, code, solo]
    )

    assert [(candidate.kind, candidate.name) for candidate in candidates[:4]] == [
        ("tribe", "@builders"),
        ("tribe", "@makers"),
        ("clan", "review"),
        ("family", "ship"),
    ]
    by_name = {candidate.name: candidate for candidate in candidates}
    assert by_name["@builders"].member_count == 3
    assert by_name["@builders"].agent_count == 1
    assert by_name["@builders"].clan_count == 1
    assert by_name["review"].member_count == 2
    assert by_name["review"].member_names == ("review.alpha", "review.beta")
    assert by_name["ship"].member_count == 2
    assert by_name["ship"].aggregate_status == "RUNNING"
    assert "@retired" not in by_name
    assert by_name["review.old"].kind == "agent"


def test_build_agent_completion_candidates_omits_empty_clan(tmp_path: Path) -> None:
    empty = _agent(
        tmp_path,
        agent_name=None,
        raw_suffix=None,
        agent_clan="empty",
        agent_clan_generation="20260718100000",
        is_clan_container=True,
    )

    assert build_agent_completion_candidates([empty]) == []


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


def test_status_style_returns_rich_parseable_styles() -> None:
    console = Console()

    for status in [
        "RUNNING",
        "STARTING",
        "WAITING",
        "DONE",
        "PLAN DONE",
        "FAILED",
        "PLAN",
        "QUESTION",
        "KILLED",
        "ARCHIVED",
        "",
    ]:
        style = status_style(status)

        Style.parse(style)
        console.get_style(style)
