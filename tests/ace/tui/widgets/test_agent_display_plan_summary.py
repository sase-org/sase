"""Plan enrichment and detail-summary tests for the agent display."""

from __future__ import annotations

import pytest

from sase.ace.tui.models.agent_associated_plan import (
    _AgentPlanEnrichment,
    PhaseBeadSummary,
)
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    build_detail_header_summary,
    build_header_text,
    cache_detail_header_summary,
    get_cached_detail_header_summary,
    should_refresh_detail_header_summary,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_plan_helpers import (
    plan_summary as _plan_summary,
)


def test_detail_summary_resolves_plan_only_in_enrichment_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="planner", step_type="bash")
    plan = _plan_summary()
    calls: list[object] = []

    def resolve(agent_arg: object) -> _AgentPlanEnrichment:
        calls.append(agent_arg)
        return _AgentPlanEnrichment("ordinary", None, plan, plan.actual_path)

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary."
        "resolve_agent_plan_enrichment",
        resolve,
    )

    summary = build_detail_header_summary(agent)

    assert summary.associated_plan is plan
    assert calls[0] is agent


def test_canonical_plan_is_removed_from_generic_artifact_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="planner", step_type="bash")
    plan = _plan_summary(actual_path="/tmp/plan.md", display_path="~/plan.md")
    other = ArtifactFilePath("notes.md", "/tmp/notes.md")
    duplicate = ArtifactFilePath("plan.md", "/tmp/plan.md", view_mode="markdown")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary."
        "resolve_agent_plan_enrichment",
        lambda *_args, **_kwargs: _AgentPlanEnrichment(
            "ordinary",
            None,
            plan,
            plan.actual_path,
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._artifact_files.artifact_file_paths",
        lambda _agent: [duplicate, other],
    )

    summary = build_detail_header_summary(agent)

    assert summary.artifact_file_paths == [other]


def test_phase_plan_is_not_exposed_as_generic_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(
        agent_name="sase-9.2",
        epic_bead_id="sase-9",
        phase_bead_id="sase-9.2",
        step_type="bash",
    )
    other = ArtifactFilePath("notes.md", "/tmp/notes.md")
    duplicate = ArtifactFilePath("epic.md", "/tmp/epic.md", view_mode="markdown")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary."
        "resolve_agent_plan_enrichment",
        lambda *_args, **_kwargs: _AgentPlanEnrichment(
            "phase",
            PhaseBeadSummary(
                id="sase-9.2",
                description="Selected phase",
                actual_plan_path="/tmp/epic.md",
                display_plan_path="epic.md",
                plan_exists=True,
                plan_readable=True,
                epic_title="Selected epic",
            ),
            None,
            "/tmp/epic.md",
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._artifact_files.artifact_file_paths",
        lambda _agent: [duplicate, other],
    )

    summary = build_detail_header_summary(agent)

    assert summary.associated_plan is None
    assert summary.artifact_file_paths == [other]


def test_cheap_header_never_resolves_or_stats_plan(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("hot render path must remain memory-only")

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan.resolve_agent_plan_enrichment",
        fail,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan._PlanFileCache.get",
        fail,
    )

    header, _ = build_header_text(make_agent(agent_name="planner"), cheap=True)

    assert "▸ PLAN" not in header.plain


def test_approval_metadata_change_invalidates_cached_plan_summary() -> None:
    class Widget:
        pass

    widget = Widget()
    agent = make_agent(
        agent_name="planner",
        archived_plan_path="/tmp/archive.md",
        plan_committed=None,
    )
    summary = DetailHeaderSummary(associated_plan=_plan_summary())

    cache_detail_header_summary(widget, agent, summary)
    assert get_cached_detail_header_summary(widget, agent) is summary

    agent.plan_committed = False

    assert get_cached_detail_header_summary(widget, agent) is None
    assert should_refresh_detail_header_summary(widget, agent)


def test_modern_phase_renders_one_frontmatter_bead_and_no_plan(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    plan = tmp_path / "plans" / "epic.md"
    plan.parent.mkdir()
    plan.write_text(
        "---\n"
        "tier: epic\n"
        "title: Role-aware metadata\n"
        "goal: Keep the complete roadmap on epic owners only.\n"
        "phases:\n"
        "  - id: core\n"
        "    title: Build metadata\n"
        "    depends_on: []\n"
        "    size: small\n"
        "  - id: render\n"
        "    title: Render phase metadata\n"
        "    depends_on: [core]\n"
        "    description: >-\n"
        "      Show only this selected\n"
        "      phase description.\n"
        "    size: medium\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    agent = make_agent(
        agent_name="sase-9.2",
        epic_bead_id="sase-9",
        phase_bead_id="sase-9.2",
        sdd_plan_path="plans/epic.md",
        plan_committed=True,
        workspace_dir=str(tmp_path),
        step_type="bash",
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan._lookup_issue",
        lambda *_args, **_kwargs: pytest.fail("modern phase must not read beads"),
    )

    summary = build_detail_header_summary(agent)
    header, _ = build_header_text(agent, summary=summary)

    assert summary.associated_plan is None
    assert "Bead:" not in header.plain
    assert "▸ BEAD · phase sase-9.2\n" in header.plain
    assert "ID:" not in header.plain
    assert header.plain.count("▸ BEAD · phase sase-9.2") == 1
    assert " Description: Show only this selected phase description.\n" in (
        header.plain
    )
    assert "   Epic Plan: plans/epic.md\n" in header.plain
    assert "  Epic Title: Role-aware metadata\n" in header.plain
    assert "▸ PLAN" not in header.plain
    assert "Goal:" not in header.plain
    assert "Path:" not in header.plain
    assert "Build metadata" not in header.plain
