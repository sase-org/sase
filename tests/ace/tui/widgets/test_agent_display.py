"""Tests for agent display helpers and followup_agents integration."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_bead import derive_agent_bead_id
from sase.ace.tui.models.artifact_indicator import (
    artifact_indicator_from_summary,
    render_artifact_indicator,
)
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin
from sase.ace.tui.widgets.prompt_panel._agent_display_hints import (
    AgentHintsDisplayMixin,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_header_text,
    get_phase_label,
    render_phase_divider,
)
from sase.bead.model import BeadTier, Issue, IssueType
from sase.core.artifact_wire import ArtifactSummaryWire, ArtifactTypeCountWire


def _make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for testing."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/test.gp",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 14, 23, 45),
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _artifact_summary() -> ArtifactSummaryWire:
    return ArtifactSummaryWire(
        artifact_id="agent-a",
        state="ok",
        total_linked_count=4,
        file_type_counts=[
            ArtifactTypeCountWire(artifact_type="chat", total_count=2),
            ArtifactTypeCountWire(artifact_type="diff", total_count=1),
        ],
        kind_counts=[
            ArtifactTypeCountWire(artifact_type="bead", total_count=1),
        ],
    )


class _FakePromptPanel(AgentDisplayMixin, AgentHintsDisplayMixin):
    """Mixin-only test double recording ``self.update(...)`` calls."""

    def __init__(self) -> None:
        self.captured: list[object] = []

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)


def _plain_of(renderable: object) -> str:
    """Flatten a prompt panel renderable into plain text for assertions."""
    if isinstance(renderable, Text):
        return renderable.plain
    if isinstance(renderable, Syntax):
        return str(renderable.code)
    if isinstance(renderable, Group):
        return "\n".join(_plain_of(child) for child in renderable.renderables)
    return str(renderable)


def _make_artifact_agent(
    tmp_path: Path,
    *,
    status: str,
    raw_xprompt: str = "Launch from @src/raw.py",
    workspace_dir: str | None = None,
) -> Agent:
    artifacts_dir = tmp_path / f"{status.lower()}-artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_xprompt.md").write_text(raw_xprompt, encoding="utf-8")
    (artifacts_dir / "01_prompt.md").write_text(
        "Expanded prompt body\n",
        encoding="utf-8",
    )
    response_path = artifacts_dir / "response.md"
    response_path.write_text("Final response body\n", encoding="utf-8")

    return _make_agent(
        status=status,
        stop_time=datetime(2024, 1, 1, 14, 30, 0),
        artifacts_dir=str(artifacts_dir),
        response_path=str(response_path),
        workspace_dir=workspace_dir,
    )


# -- xprompt rendering --------------------------------------------------------


def test_agent_row_renders_shared_artifact_indicator() -> None:
    agent = _make_agent(agent_name="agent-a")
    indicator = artifact_indicator_from_summary(_artifact_summary())
    assert indicator is not None

    left, _, _ = format_agent_option(
        agent,
        0,
        is_selected=False,
        artifact_indicator=indicator,
    )

    shared = render_artifact_indicator(indicator)
    assert shared.plain == "art 4 diff1 chat2 bead1"
    assert left.plain.endswith(f"  {shared.plain}")
    row_tail = left.plain.rfind(shared.plain)
    row_styles = {span.style for span in left.spans if span.end > row_tail}
    assert {span.style for span in shared.spans}.issubset(row_styles)


def test_workflow_parent_and_child_rows_render_artifact_indicators() -> None:
    parent_indicator = artifact_indicator_from_summary(
        ArtifactSummaryWire(
            artifact_id="workflow-agent",
            state="ok",
            total_linked_count=1,
            file_type_counts=[
                ArtifactTypeCountWire(artifact_type="plan", total_count=1),
            ],
        )
    )
    child_indicator = artifact_indicator_from_summary(
        ArtifactSummaryWire(
            artifact_id="workflow-child",
            state="ok",
            total_linked_count=1,
            file_type_counts=[
                ArtifactTypeCountWire(artifact_type="diff", total_count=1),
            ],
        )
    )
    assert parent_indicator is not None
    assert child_indicator is not None

    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        workflow="deploy",
        cl_name="demo",
        raw_suffix="20260506120000",
    )
    child = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="demo",
        parent_workflow="deploy",
        parent_timestamp="20260506120000",
        step_type="agent",
        step_index=0,
        total_steps=2,
    )

    parent_left, _, _ = format_agent_option(
        parent,
        0,
        is_selected=False,
        artifact_indicator=parent_indicator,
    )
    child_left, _, _ = format_agent_option(
        child,
        1,
        is_selected=False,
        artifact_indicator=child_indicator,
    )

    assert "art 1 plan1" in parent_left.plain
    assert "1/2" in child_left.plain
    assert "art 1 diff1" in child_left.plain


class TestAgentXPromptRendering:
    def test_done_agent_renders_raw_xprompt(self, tmp_path: Path) -> None:
        panel = _FakePromptPanel()
        agent = _make_artifact_agent(tmp_path, status="DONE")

        panel.update_display(agent)

        plain = _plain_of(panel.captured[-1])
        assert "AGENT XPROMPT" in plain
        assert "Launch from @src/raw.py" in plain
        assert "AGENT PROMPT" in plain
        assert "AGENT CHAT" in plain

    def test_failed_agent_renders_raw_xprompt(self, tmp_path: Path) -> None:
        panel = _FakePromptPanel()
        agent = _make_artifact_agent(tmp_path, status="FAILED")

        panel.update_display(agent)

        plain = _plain_of(panel.captured[-1])
        assert "AGENT XPROMPT" in plain
        assert "Launch from @src/raw.py" in plain
        assert "AGENT PROMPT" in plain
        assert "AGENT CHAT" in plain

    def test_hint_mode_renders_raw_xprompt_for_terminal_agent(
        self,
        tmp_path: Path,
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        panel = _FakePromptPanel()
        agent = _make_artifact_agent(
            tmp_path,
            status="DONE",
            workspace_dir=str(workspace_dir),
        )

        hint_mappings = panel.update_display_with_hints(agent)

        plain = _plain_of(panel.captured[-1])
        assert "AGENT XPROMPT" in plain
        assert "[1] @src/raw.py" in plain
        assert hint_mappings[1] == str(workspace_dir / "src/raw.py")


# -- _get_phase_label ---------------------------------------------------------


class TestGetPhaseLabel:
    def test_plan(self) -> None:
        agent = _make_agent(role_suffix=".plan")
        assert get_phase_label(agent) == "PLANNER"

    def test_code(self) -> None:
        agent = _make_agent(role_suffix=".code")
        assert get_phase_label(agent) == "CODER"

    def test_questions(self) -> None:
        agent = _make_agent(role_suffix=".q")
        assert get_phase_label(agent) == "QUESTIONS"

    def test_epic(self) -> None:
        agent = _make_agent(role_suffix=".epic")
        assert get_phase_label(agent) == "EPIC"

    def test_feedback_round_2(self) -> None:
        agent = _make_agent(role_suffix=".2")
        assert get_phase_label(agent) == "PLANNER (round 2)"

    def test_feedback_round_10(self) -> None:
        agent = _make_agent(role_suffix=".10")
        assert get_phase_label(agent) == "PLANNER (round 10)"

    def test_no_suffix(self) -> None:
        agent = _make_agent(role_suffix=None)
        assert get_phase_label(agent) == "AGENT"

    def test_unknown_suffix(self) -> None:
        agent = _make_agent(role_suffix=".xyz")
        assert get_phase_label(agent) == "AGENT"


# -- derive_agent_bead_id / header metadata ----------------------------------


class TestAgentBeadMetadata:
    def test_phase_agent_name_renders_bead(self) -> None:
        agent = _make_agent(agent_name="sase-x.3")

        assert derive_agent_bead_id(agent) == "sase-x.3"
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_land_agent_name_renders_epic_bead(self) -> None:
        agent = _make_agent(agent_name="sase-x.land")

        assert derive_agent_bead_id(agent) == "sase-x"
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @sase-x.land\nBead: sase-x\n" in header.plain

    def test_exact_epic_agent_name_renders_epic_bead(self) -> None:
        agent = _make_agent(agent_name="sase-x")

        assert derive_agent_bead_id(agent) == "sase-x"
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @sase-x\nBead: sase-x\n" in header.plain

    def test_dismissed_phase_agent_name_uses_underlying_bead(self) -> None:
        agent = _make_agent(agent_name="260428.sase-x.3")

        assert derive_agent_bead_id(agent) == "sase-x.3"
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @260428.sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_ordinary_agent_name_omits_bead(self) -> None:
        agent = _make_agent(agent_name="reviewer")

        assert derive_agent_bead_id(agent) is None
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @reviewer\n" in header.plain
        assert "Bead:" not in header.plain

    def test_full_header_renders_bead_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(agent_name="sase-x.3")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: Issue(
                id=bead_id,
                title="Phase title",
                description="First line\n\n second\tline ",
            ),
        )

        header, _ = build_header_text(agent, cheap=False)

        assert "Name: @sase-x.3\nBead: sase-x.3 - First line second line\n" in (
            header.plain
        )

    def test_full_header_passes_agent_project_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(
            agent_name="zorg-4.3.6",
            project_file="/home/me/.sase/projects/zorg/zorg.gp",
        )
        seen_project_names: list[str | None] = []

        def lookup(bead_id: str, *, project_name: str | None = None) -> Issue | None:
            seen_project_names.append(project_name)
            return Issue(
                id=bead_id,
                title="Phase 6: count() MVP And Final Epic Hardening",
                description="",
            )

        monkeypatch.setattr("sase.agent.bead_display._lookup_bead_issue", lookup)

        header, _ = build_header_text(agent, cheap=False)

        assert seen_project_names == ["zorg"]
        assert (
            "Name: @zorg-4.3.6\n"
            "Bead: zorg-4.3.6 - Phase 6: count() MVP And Final Epic Hardening\n"
        ) in header.plain

    def test_full_header_falls_back_for_empty_bead_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(agent_name="sase-x.3")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: Issue(
                id=bead_id,
                title="Phase title",
                description=" \n\t ",
            ),
        )

        header, _ = build_header_text(agent, cheap=False)

        assert "Name: @sase-x.3\nBead: sase-x.3 - Phase title\n" in header.plain

    def test_full_header_falls_back_for_missing_bead(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(agent_name="sase-x.3")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: None,
        )

        header, _ = build_header_text(agent, cheap=False)

        assert "Name: @sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_cheap_header_does_not_lookup_bead_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(agent_name="sase-x.3")

        def fail_lookup(bead_id: str) -> Issue | None:
            raise AssertionError("cheap header must not touch bead storage")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            fail_lookup,
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_full_land_header_uses_plan_title_when_description_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(agent_name="sase-x.land")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: Issue(
                id=bead_id,
                title=" Make `sase bead` Fast With `sase-core` ",
                description=" \n\t ",
            ),
        )

        header, _ = build_header_text(agent, cheap=False)

        assert (
            "Name: @sase-x.land\n"
            "Bead: sase-x - Land epic: Make `sase bead` Fast With `sase-core`\n"
        ) in header.plain

    def test_full_exact_land_header_uses_epic_title_when_description_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(agent_name="sase-x")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: Issue(
                id=bead_id,
                title=" Make `sase bead` Fast With `sase-core` ",
                issue_type=IssueType.PLAN,
                tier=BeadTier.EPIC,
                description=" \n\t ",
            ),
        )

        header, _ = build_header_text(agent, cheap=False)

        assert (
            "Name: @sase-x\n"
            "Bead: sase-x - Land epic: Make `sase bead` Fast With `sase-core`\n"
        ) in header.plain

    def test_full_land_header_prefers_explicit_plan_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _make_agent(agent_name="sase-x.land")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: Issue(
                id=bead_id,
                title="Plan title",
                description="Use the explicit plan description",
            ),
        )

        header, _ = build_header_text(agent, cheap=False)

        assert (
            "Name: @sase-x.land\nBead: sase-x - Use the explicit plan description\n"
        ) in header.plain


# -- agent list bead badge ----------------------------------------------------


class TestAgentListBeadBadge:
    def test_phase_agent_row_renders_bead_badge(self) -> None:
        agent = _make_agent(agent_name="sase-x.3")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ @sase-x.3" in left.plain

    def test_land_agent_row_renders_epic_bead_badge(self) -> None:
        agent = _make_agent(agent_name="sase-x.land")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ @sase-x.land" in left.plain

    def test_exact_land_agent_row_renders_epic_bead_badge(self) -> None:
        agent = _make_agent(agent_name="sase-x")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ @sase-x" in left.plain

    def test_dismissed_phase_agent_row_renders_underlying_bead_badge(self) -> None:
        agent = _make_agent(agent_name="260428.sase-x.3")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ @260428.sase-x.3" in left.plain

    def test_ordinary_agent_row_omits_bead_badge(self) -> None:
        agent = _make_agent(agent_name="reviewer")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain

    def test_bead_badge_flows_from_fold_annotation_to_agent_name(self) -> None:
        agent = _make_agent(agent_name="sase-x.3", tag="pinned")

        left, _, _ = format_agent_option(
            agent, 0, is_selected=False, fold_annotation="×3"
        )

        assert "(RUNNING)×3 ◆ @sase-x.3" in left.plain
        assert "@pinned" not in left.plain


class TestAwareWaitUntilRendering:
    def test_agent_row_renders_aware_wait_until_countdown(self) -> None:
        wait_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        agent = _make_agent(status="WAITING", wait_until=wait_until)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "WAITING (until " in left.plain
        assert "," in left.plain

    def test_header_renders_aware_wait_until_countdown(self) -> None:
        wait_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        agent = _make_agent(status="WAITING", wait_until=wait_until)

        header, _ = build_header_text(agent, cheap=True)

        assert "Waiting for: until " in header.plain
        assert " left)" in header.plain


# -- _render_phase_divider ----------------------------------------------------


class TestRenderPhaseDivider:
    def test_contains_label(self) -> None:
        divider = render_phase_divider("PLANNER", datetime(2024, 1, 1, 14, 23, 45))
        assert "PLANNER" in divider.plain

    def test_contains_time_format(self) -> None:
        divider = render_phase_divider("CODER", datetime(2024, 1, 1, 14, 23, 45))
        assert re.search(r"\d{2}:\d{2}:\d{2}", divider.plain)

    def test_none_start_time(self) -> None:
        divider = render_phase_divider("AGENT", None)
        assert "??:??:??" in divider.plain

    def test_bold_purple_label(self) -> None:
        divider = render_phase_divider("PLANNER", datetime(2024, 1, 1))
        has_bold = any(
            "bold" in str(s.style) and "af87ff" in str(s.style).lower()
            for s in divider._spans
        )
        assert has_bold


# -- followup_agents field -----------------------------------------------------


class TestFollowupAgentsField:
    def test_defaults_empty(self) -> None:
        assert _make_agent().followup_agents == []

    def test_excluded_from_bundle(self) -> None:
        agent = _make_agent()
        agent.followup_agents.append(_make_agent(cl_name="child"))
        assert "followup_agents" not in agent.to_bundle_dict()

    def test_roundtrip_resets(self) -> None:
        agent = _make_agent()
        agent.followup_agents.append(_make_agent(cl_name="child"))
        restored = Agent.from_bundle_dict(agent.to_bundle_dict())
        assert restored.followup_agents == []


# -- _apply_status_overrides followup population ------------------------------


class TestLoaderFollowupPopulation:
    def test_coder_attached_to_parent(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides

        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            raw_suffix="20240101142345",
            role_suffix=".plan",
            status="DONE",
        )
        coder = _make_agent(
            parent_timestamp="20240101142345",
            role_suffix=".code",
            status="RUNNING",
        )
        _apply_status_overrides([parent, coder])
        assert len(parent.followup_agents) == 1
        assert parent.followup_agents[0] is coder

    def test_feedback_attached(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides

        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            raw_suffix="20240101142345",
            role_suffix=".plan",
            status="DONE",
        )
        fb = _make_agent(
            parent_timestamp="20240101142345",
            role_suffix=".2",
            status="DONE",
        )
        _apply_status_overrides([parent, fb])
        assert len(parent.followup_agents) == 1
        assert parent.followup_agents[0] is fb

    def test_sorted_chronologically(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides

        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            raw_suffix="20240101142345",
            role_suffix=".plan",
            status="DONE",
        )
        coder = _make_agent(
            parent_timestamp="20240101142345",
            role_suffix=".code",
            status="RUNNING",
            start_time=datetime(2024, 1, 1, 16, 0),
        )
        fb = _make_agent(
            parent_timestamp="20240101142345",
            role_suffix=".2",
            status="DONE",
            start_time=datetime(2024, 1, 1, 15, 0),
        )
        _apply_status_overrides([parent, coder, fb])
        assert parent.followup_agents[0] is fb
        assert parent.followup_agents[1] is coder

    def test_workflow_child_not_attached(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides

        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            raw_suffix="20240101142345",
            role_suffix=".plan",
            status="DONE",
        )
        step = _make_agent(
            parent_timestamp="20240101142345",
            parent_workflow="test_wf",
            step_type="agent",
            status="DONE",
        )
        _apply_status_overrides([parent, step])
        assert parent.followup_agents == []
