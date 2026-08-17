"""Tests for shared agent completion candidates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.style import Style

import sase.ace.tui.models.agent_family_preview_cache as family_preview_cache
from sase.agent_family_plan_preview import AgentFamilyPlanPreview
from sase.ace.tui.agent_completion import (
    build_agent_completion_candidates,
    filter_agent_completion_candidates,
    status_style,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)
from sase.core.time import local_now


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
        "start_time": local_now(),
        "raw_suffix": "260624_120000",
        "agent_name": "coder",
        "artifacts_dir": artifacts_dir,
    }
    defaults.update(overrides)
    return Agent(**defaults)


def _plan_preview(title: str) -> AgentFamilyPlanPreview:
    return AgentFamilyPlanPreview(
        kind="epic",
        title=title,
        goal="Preview goal",
        parent_title=None,
        phase_count=2,
        wave_count=1,
        phase_titles=("Preview", "Rows"),
        phase_ids=("preview", "rows"),
        phase_sizes=("medium", "medium"),
        size=None,
    )


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


def test_family_completion_candidate_attaches_cached_plan_preview(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    preview = _plan_preview("Plan-aware family preview")
    family = _agent(
        tmp_path,
        agent_name="completion.plan",
        agent_family="completion",
        agent_family_role="root",
        plan_chain_root=True,
        raw_prompt="Fallback launch prompt",
    )

    monkeypatch.setattr(
        "sase.ace.tui._agent_completion_candidates.cached_family_plan_preview",
        lambda _agent: preview,
    )

    candidates = build_agent_completion_candidates([family])
    candidate = candidates[0]

    assert candidate.plan_preview is preview
    assert "Plan-aware family preview" in candidate.search_aliases
    assert filter_agent_completion_candidates(candidates, "Plan-aware") == [candidate]
    assert "plan-aware family preview" in candidate.search_text


def test_family_completion_candidate_uses_first_member_prompt_when_root_is_empty(
    tmp_path: Path,
) -> None:
    family = _agent(
        tmp_path,
        agent_name="ship--plan",
        raw_suffix="20260718110000",
        agent_family="ship",
        agent_family_role="root",
        plan_chain_root=True,
    )
    code = _agent(
        tmp_path,
        agent_name="ship--code",
        raw_suffix="20260718110001",
        agent_family="ship",
        agent_family_role="code",
        parent_timestamp=family.raw_suffix,
        raw_prompt="Implement initial agent prompt fallback",
    )
    family.followup_agents.append(code)

    candidates = build_agent_completion_candidates([family, code])
    candidate = next(candidate for candidate in candidates if candidate.name == "ship")

    assert candidate.prompt_snippet == "Implement initial agent prompt fallback"


def test_family_completion_candidate_build_does_not_resolve_plan_or_bead_io(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    family = _agent(
        tmp_path,
        agent_name="ship--plan",
        agent_family="ship",
        agent_family_role="root",
        plan_chain_root=True,
        raw_prompt="Build candidates without resolver I/O",
    )

    def fail_resolver(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("completion candidate build must not resolve previews")

    monkeypatch.setattr(
        family_preview_cache,
        "resolve_agent_plan_enrichment",
        fail_resolver,
    )

    candidates = build_agent_completion_candidates([family])

    assert candidates[0].name == "ship"
    assert candidates[0].plan_preview is None


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
