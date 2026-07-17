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

    assert "Bead: sase-9.2\n" in cheap_header.plain
    assert summary.associated_plan is None
    assert summary.artifact_file_paths == [other]
    assert "Bead: sase-9.2 - Show only the recovered phase description.\n" in (
        header.plain
    )
    assert "SASE CONTEXT" in header.plain
    assert "▸ PLAN" not in header.plain
    assert "Parent epic roadmap" not in header.plain
    assert "Never expose this complete roadmap" not in header.plain
    assert "epic.md" not in header.plain
    assert "notes.md" in header.plain
