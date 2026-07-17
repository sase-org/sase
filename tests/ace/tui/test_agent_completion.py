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
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup


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
        tag="review",
        raw_prompt="%wait(old, time=5m) #gh:sase Redesign wait completion\nwith rows",
    )
    duplicate = _agent(tmp_path, agent_name="completion", raw_suffix="260624_120001")
    unnamed = _agent(tmp_path, agent_name=None, raw_suffix="260624_120002")
    other = _agent(tmp_path, agent_name="verifier", raw_suffix="260624_120003")

    candidates = build_agent_completion_candidates(
        [family, duplicate, unnamed, other],
        exclude_identity=other.identity,
    )

    assert [candidate.name for candidate in candidates] == ["completion"]
    candidate = candidates[0]
    assert candidate.label == "completion.plan"
    assert candidate.model == "codex / gpt-5@high"
    assert candidate.tag == "@review"
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


def test_visible_agent_completion_agents_aggregates_all_panel_widgets(
    tmp_path: Path,
) -> None:
    untagged = _agent(tmp_path, agent_name="untagged", raw_suffix="260624_120020")
    alpha = _agent(
        tmp_path,
        agent_name="alpha",
        raw_suffix="260624_120021",
        tag="alpha",
    )
    alpha_extra = _agent(
        tmp_path,
        agent_name="alpha-extra",
        raw_suffix="260624_120022",
        tag="alpha",
    )
    beta = _agent(
        tmp_path,
        agent_name="beta",
        raw_suffix="260624_120023",
        tag="beta",
    )
    app = _CompletionApp(
        [untagged, alpha, alpha_extra, beta],
        {
            0: [untagged],
            1: [alpha, alpha_extra],
            2: [beta, alpha],
        },
    )
    app._panel_group.focused_idx = 1

    assert visible_agent_completion_agents(app) == [
        untagged,
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
