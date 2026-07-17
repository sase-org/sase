"""Header regressions for phase workers with partially damaged metadata."""

from pathlib import Path

import pytest

from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    build_detail_header_summary,
    build_header_text,
    cache_detail_header_summary,
    get_cached_detail_header_summary,
    should_refresh_detail_header_summary,
)
from sase.bead.model import BeadTier, Issue, IssueType
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def test_phase_role_change_invalidates_cached_plan_summary() -> None:
    class Widget:
        pass

    widget = Widget()
    agent = make_agent(
        agent_name="sase-9.2",
        epic_bead_id="sase-9",
        sdd_plan_path="/tmp/epic.md",
        plan_committed=True,
    )
    summary = DetailHeaderSummary()

    cache_detail_header_summary(widget, agent, summary)
    assert get_cached_detail_header_summary(widget, agent) is summary

    agent.agent_family_role = "phase"

    assert get_cached_detail_header_summary(widget, agent) is None
    assert should_refresh_detail_header_summary(widget, agent)


def test_project_file_change_invalidates_cached_phase_association() -> None:
    class Widget:
        pass

    widget = Widget()
    agent = make_agent(
        agent_name="sase-9.2",
        project_file="/tmp/projects/alpha/alpha.sase",
    )
    summary = DetailHeaderSummary()

    cache_detail_header_summary(widget, agent, summary)
    assert get_cached_detail_header_summary(widget, agent) is summary

    agent.project_file = "/tmp/projects/beta/beta.sase"

    assert get_cached_detail_header_summary(widget, agent) is None
    assert should_refresh_detail_header_summary(widget, agent)


def test_damaged_explicit_phase_role_suppresses_epic_plan_and_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = tmp_path / "plans" / "epic.md"
    plan.parent.mkdir()
    plan.write_text(
        "---\n"
        "tier: epic\n"
        "title: Parent epic roadmap\n"
        "goal: Never expose this complete roadmap on a phase.\n"
        "phases:\n"
        "  - id: core\n"
        "    title: Build metadata\n"
        "    depends_on: []\n"
        "  - id: render\n"
        "    title: Render phase metadata\n"
        "    depends_on: [core]\n"
        "    description: Show only the recovered phase description.\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    agent = make_agent(
        agent_name="sase-9.2",
        agent_family_role="phase",
        epic_bead_id="sase-9",
        sdd_plan_path="plans/epic.md",
        plan_committed=True,
        workspace_dir=str(tmp_path),
        step_type="bash",
    )
    duplicate = ArtifactFilePath(
        "epic.md",
        str(plan.resolve()),
        view_mode="markdown",
    )
    other = ArtifactFilePath("notes.md", str(tmp_path / "notes.md"))
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._artifact_files.artifact_file_paths",
        lambda _agent: [duplicate, other],
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan._lookup_issue",
        lambda *_args, **_kwargs: pytest.fail("explicit phase must not read beads"),
    )

    cheap_header, _ = build_header_text(agent, cheap=True)
    summary = build_detail_header_summary(agent)
    header, _ = build_header_text(agent, summary=summary)

    assert "Bead:" not in cheap_header.plain
    assert "▸ BEAD" not in cheap_header.plain
    assert summary.associated_plan is None
    assert summary.artifact_file_paths == [other]
    assert "Bead:" not in header.plain
    assert "          ID: sase-9.2\n" in header.plain
    assert " Description: Show only the recovered phase description.\n" in header.plain
    assert "   Epic Plan: plans/epic.md\n" in header.plain
    assert "  Epic Title: Parent epic roadmap\n" in header.plain
    assert "SASE CONTEXT" in header.plain
    assert "▸ BEAD · phase" in header.plain
    assert "▸ PLAN" not in header.plain
    assert "Never expose this complete roadmap" not in header.plain
    assert "notes.md" in header.plain


def test_confirmed_legacy_phase_uses_bead_lane_and_suppresses_old_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = tmp_path / "plans" / "legacy epic.md"
    plan.parent.mkdir()
    plan.write_text(
        "---\n"
        "tier: epic\n"
        "title: Legacy phase context\n"
        "goal: Keep the roadmap private to epic owners.\n"
        "phases:\n"
        "  - id: core\n"
        "    title: Core phase\n"
        "    depends_on: []\n"
        "    description: Show this confirmed legacy phase only.\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    phase = Issue(
        id="sase-legacy.1",
        title="Core phase",
        issue_type=IssueType.PHASE,
        parent_id="sase-legacy",
    )
    epic = Issue(
        id="sase-legacy",
        title="Legacy epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans/legacy epic.md",
    )
    issues = {phase.id: phase, epic.id: epic}
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan._lookup_issue",
        lambda _agent, bead_id, **_kwargs: issues.get(bead_id),
    )
    agent = make_agent(
        agent_name="sase-legacy.1",
        workspace_dir=str(tmp_path),
        step_type="bash",
    )

    summary = build_detail_header_summary(agent)
    header, _ = build_header_text(agent, summary=summary)

    assert summary.phase_bead is not None
    assert "Bead:" not in header.plain
    assert "▸ BEAD · phase\n" in header.plain
    assert "          ID: sase-legacy.1\n" in header.plain
    assert " Description: Show this confirmed legacy phase only.\n" in header.plain
    assert "   Epic Plan: plans/legacy epic.md\n" in header.plain
    assert "  Epic Title: Legacy phase context\n" in header.plain
    assert "▸ PLAN" not in header.plain
    assert "Keep the roadmap private" not in header.plain
