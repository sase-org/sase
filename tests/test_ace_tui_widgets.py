"""Tests for the ace TUI widgets (section builders and TabBar)."""

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.changespec import ChangeSpec, CommentEntry, CommitEntry, HookEntry
from sase.ace.tui import AceApp
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import ChangeSpecInfoPanel, TabBar
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.commits_builder import _should_show_commits_drawers
from sase.ace.tui.widgets.prompt_panel import (
    AgentPromptPanel,
    load_embedded_workflows,
)


def _make_changespec(
    name: str = "test_feature",
    description: str = "Test description",
    status: str = "Ready",
    cl: str | None = None,
    parent: str | None = None,
    file_path: str = "/tmp/test.gp",
    commits: list[CommitEntry] | None = None,
    hooks: list[HookEntry] | None = None,
    comments: list[CommentEntry] | None = None,
) -> ChangeSpec:
    """Create a mock ChangeSpec for testing."""
    return ChangeSpec(
        name=name,
        description=description,
        parent=parent,
        cl=cl,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path=file_path,
        line_number=1,
        commits=commits,
        hooks=hooks,
        comments=comments,
    )


# --- _should_show_commits_drawers Tests ---


def test_should_show_commits_drawers_expanded() -> None:
    """All entries show drawers when expanded."""
    entry = CommitEntry(number=5, note="test")
    changespec = _make_changespec(
        commits=[
            CommitEntry(number=1, note="first"),
            CommitEntry(number=5, note="test"),
        ]
    )

    assert _should_show_commits_drawers(entry, changespec, FoldLevel.EXPANDED)


def test_should_show_commits_drawers_collapsed_intermediate_hidden() -> None:
    """Intermediate entries hide drawers when collapsed."""
    entry = CommitEntry(number=3, note="intermediate")
    changespec = _make_changespec(
        commits=[
            CommitEntry(number=1, note="first"),
            CommitEntry(number=3, note="intermediate"),
            CommitEntry(number=5, note="current"),
        ]
    )

    assert not _should_show_commits_drawers(entry, changespec, FoldLevel.COLLAPSED)


def test_should_show_commits_drawers_collapsed_old_proposal_hidden() -> None:
    """Old proposal entries (not for max ID) hide drawers when collapsed."""
    entry = CommitEntry(number=2, note="old proposal", proposal_letter="a")
    changespec = _make_changespec(
        commits=[
            CommitEntry(number=1, note="first"),
            CommitEntry(number=2, note="second"),
            CommitEntry(number=2, note="old proposal", proposal_letter="a"),
            CommitEntry(number=5, note="current"),
        ]
    )

    assert not _should_show_commits_drawers(entry, changespec, FoldLevel.COLLAPSED)


def test_should_show_commits_drawers_collapsed_multiple_proposals_shown() -> None:
    """Multiple proposals for max ID all show drawers when collapsed."""
    changespec = _make_changespec(
        commits=[
            CommitEntry(number=1, note="first"),
            CommitEntry(number=3, note="current"),
            CommitEntry(number=3, note="proposal a", proposal_letter="a"),
            CommitEntry(number=3, note="proposal b", proposal_letter="b"),
        ]
    )

    entry_a = CommitEntry(number=3, note="proposal a", proposal_letter="a")
    entry_b = CommitEntry(number=3, note="proposal b", proposal_letter="b")

    assert _should_show_commits_drawers(entry_a, changespec, FoldLevel.COLLAPSED)
    assert _should_show_commits_drawers(entry_b, changespec, FoldLevel.COLLAPSED)


# --- TabBar Widget Tests ---


def test_tab_bar_update_tab_to_agents() -> None:
    """Test that update_tab changes the current tab to agents."""
    tab_bar = TabBar()
    tab_bar.update_tab("agents")
    assert tab_bar._current_tab == "agents"


def test_info_panel_fold_indicator_hidden_when_all_collapsed() -> None:
    """No fold indicator when all sections are collapsed (default)."""
    panel = ChangeSpecInfoPanel()
    content = panel._build_content()
    assert "▸" not in content.plain
    assert "▾" not in content.plain
    assert "▼" not in content.plain


def test_info_panel_fold_indicator_shown_when_any_expanded() -> None:
    """Fold indicator appears when any section is non-collapsed."""
    panel = ChangeSpecInfoPanel()
    panel._fold_commits = FoldLevel.EXPANDED
    content = panel._build_content()
    # c▾h▸m▸ (labels interleaved with indicators)
    assert "c▾" in content.plain
    assert "h▸" in content.plain
    assert "m▸" in content.plain


def test_info_panel_fold_indicator_all_fully_expanded() -> None:
    """All sections fully expanded shows three heavy down arrows."""
    panel = ChangeSpecInfoPanel()
    panel._fold_commits = FoldLevel.FULLY_EXPANDED
    panel._fold_hooks = FoldLevel.FULLY_EXPANDED
    panel._fold_mentors = FoldLevel.FULLY_EXPANDED
    content = panel._build_content()
    assert "c▼" in content.plain
    assert "h▼" in content.plain
    assert "m▼" in content.plain


def test_info_panel_fold_indicator_mixed_states() -> None:
    """Mixed fold states show correct character per section."""
    panel = ChangeSpecInfoPanel()
    panel._fold_commits = FoldLevel.FULLY_EXPANDED
    panel._fold_hooks = FoldLevel.COLLAPSED
    panel._fold_mentors = FoldLevel.EXPANDED
    content = panel._build_content()
    assert "c▼" in content.plain
    assert "h▸" in content.plain
    assert "m▾" in content.plain


# --- _get_prompt_content Tests ---


def _make_agent(
    artifacts_dir: str | None = None,
    parent_workflow: str | None = None,
    step_name: str | None = None,
    step_type: str | None = None,
    step_output: dict[str, Any] | None = None,
) -> Agent:
    """Create a minimal Agent for prompt panel testing."""
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        artifacts_dir=artifacts_dir,
        parent_workflow=parent_workflow,
        step_name=step_name,
        step_type=step_type,
        step_output=step_output,
    )


def test_get_prompt_content_workflow_child_filters_by_step(
    tmp_path: Path,
) -> None:
    """Workflow child agent gets its own step's prompt, not the most recent."""
    # Create prompt files in shared artifacts dir; make plan newer than api_research
    api_research_file = tmp_path / "workflow-olcr-api_research_prompt.md"
    api_research_file.write_text("api_research prompt content")

    # Ensure plan prompt has a later mtime
    time.sleep(0.05)
    plan_file = tmp_path / "workflow-olcr-plan_prompt.md"
    plan_file.write_text("plan prompt content")

    agent = _make_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="api_research",
    )

    panel = AgentPromptPanel.__new__(AgentPromptPanel)
    result = panel._get_prompt_content(agent)

    assert result == "api_research prompt content"


def test_get_prompt_content_step_filter_no_substring_match(
    tmp_path: Path,
) -> None:
    """Step name 'research' must not match '-api_research_prompt.md'."""
    api_research_file = tmp_path / "workflow-olcr-api_research_prompt.md"
    api_research_file.write_text("api_research prompt")

    agent = _make_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="research",
    )

    panel = AgentPromptPanel.__new__(AgentPromptPanel)
    result = panel._get_prompt_content(agent)

    # No step-specific match, so falls back to most recent (the only file)
    assert result == "api_research prompt"


# --- Parallel step display Tests ---


def test_parallel_step_does_not_show_agent_prompt(tmp_path: Path) -> None:
    """Parallel workflow steps should show STEP OUTPUT, not AGENT PROMPT."""
    # Create a prompt file that would be found if parallel wasn't filtered
    prompt_file = tmp_path / "workflow-olcr-research_prompt.md"
    prompt_file.write_text("wrong prompt content")

    agent = _make_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="research",
        step_type="parallel",
        step_output={"_data": "parallel output data"},
    )

    panel = AgentPromptPanel.__new__(AgentPromptPanel)

    with patch.object(panel, "update") as mock_update:
        panel.update_display(agent)

        assert mock_update.called
        call_args = mock_update.call_args[0]
        rendered = call_args[0]

        # The rendered output should be a Group containing header_text + output_syntax
        from rich.console import Group

        assert isinstance(rendered, Group)
        renderables = list(rendered.renderables)

        # First renderable is the header Text - check it contains STEP OUTPUT
        # but NOT AGENT PROMPT
        header_text = renderables[0]
        header_str = str(header_text)
        assert "STEP OUTPUT" in header_str
        assert "AGENT PROMPT" not in header_str


def test_parallel_step_no_output_shows_placeholder() -> None:
    """Parallel step with no output shows 'No output available.' message."""
    agent = _make_agent(
        parent_workflow="olcr",
        step_name="research",
        step_type="parallel",
    )

    panel = AgentPromptPanel.__new__(AgentPromptPanel)

    with patch.object(panel, "update") as mock_update:
        panel.update_display(agent)

        assert mock_update.called
        call_args = mock_update.call_args[0]
        rendered = call_args[0]

        # update is called with a Group of renderables
        from rich.console import Group

        assert isinstance(rendered, Group)
        header_str = "\n".join(str(r) for r in rendered.renderables)
        assert "STEP OUTPUT" in header_str
        assert "No output available." in header_str
        assert "AGENT PROMPT" not in header_str


async def test_update_display_expands_prompt_for_done_workflow_without_diff() -> None:
    """Done top-level workflow (non-agent) without diff_path should expand prompt, not thinking."""
    from sase.ace.tui.widgets.agent_detail import AgentDetail
    from textual.app import App, ComposeResult

    class _TestApp(App[None]):
        def compose(self) -> ComposeResult:
            yield AgentDetail(id="agent-detail-panel")

    app = _TestApp()
    async with app.run_test():
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="test_cl",
            project_file="/tmp/test.gp",
            status="DONE",
            start_time=None,
            workflow="my_workflow",
        )
        # Sanity: top-level workflow is NOT a workflow child or agent entry
        assert not agent.is_workflow_child
        assert not agent.appears_as_agent
        assert not agent.is_agent_entry
        assert agent.diff_path is None

        detail.update_display(agent)

        diff_scroll = detail.query_one("#agent-file-scroll")
        thinking_scroll = detail.query_one("#agent-thinking-scroll")
        prompt_scroll = detail.query_one("#agent-prompt-scroll")
        assert diff_scroll.has_class("hidden")
        assert thinking_scroll.has_class("hidden")
        assert prompt_scroll.has_class("expanded")
        assert not detail.is_thinking_visible()


async def test_tab_bar_integration_tab_key() -> None:
    """Test that pressing TAB key cycles through all tabs."""
    mock_changespecs = [_make_changespec()]
    with (
        patch(
            "sase.ace.changespec.find_all_changespecs",
            return_value=mock_changespecs,
        ),
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        app = AceApp(query="test_feature", refresh_interval=0)
        async with app.run_test() as pilot:
            # Initial state - changespecs tab
            assert app.current_tab == "changespecs"
            tab_bar = app.query_one("#tab-bar", TabBar)
            assert tab_bar._current_tab == "changespecs"

            # Press TAB to switch to agents
            await pilot.press("tab")
            assert app.current_tab == "agents"
            assert tab_bar._current_tab == "agents"

            # Press TAB to switch to axe
            await pilot.press("tab")
            assert app.current_tab == "axe"
            assert tab_bar._current_tab == "axe"

            # Press TAB to cycle back to changespecs
            await pilot.press("tab")
            assert app.current_tab == "changespecs"
            assert tab_bar._current_tab == "changespecs"


# --- Embedded Workflows Tests ---


def testload_embedded_workflows_empty(tmp_path: Path) -> None:
    """No embedded_workflows.json file returns None."""
    agent = _make_agent(artifacts_dir=str(tmp_path))
    result = load_embedded_workflows(agent)

    assert result is None


def testload_embedded_workflows_no_artifacts_dir() -> None:
    """Agent with no artifacts_dir returns None."""
    agent = _make_agent(artifacts_dir=None)
    result = load_embedded_workflows(agent)

    assert result is None


def test_embedded_workflows_displayed_in_metadata(tmp_path: Path) -> None:
    """Verify 'Embedded Workflows:' appears in rendered output."""
    metadata = [
        {"name": "propose", "args": {"note": "blah"}},
        {"name": "cl", "args": {}},
    ]
    metadata_file = tmp_path / "embedded_workflows_main.json"
    metadata_file.write_text(json.dumps(metadata))

    agent = _make_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="main",
    )

    panel = AgentPromptPanel.__new__(AgentPromptPanel)

    with patch.object(panel, "update") as mock_update:
        panel.update_display(agent)

        assert mock_update.called
        call_args = mock_update.call_args[0]
        rendered = call_args[0]

        # Extract text content from the rendered output
        rendered_str = str(rendered)
        assert "Embedded Workflows:" in rendered_str
        assert "propose(note=blah), cl" in rendered_str


# --- Follow-up reply aggregation Tests ---


def _make_plan_agent(
    *,
    raw_suffix: str = "20260330120000",
    role_suffix: str = ".plan",
    status: str = "DONE",
    artifacts_dir: str | None = None,
    response_content: str | None = None,
) -> Agent:
    """Create a top-level plan agent for aggregation tests."""
    from datetime import datetime

    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test_cl",
        project_file="/tmp/test.gp",
        status=status,
        start_time=datetime(2026, 3, 30, 12, 0, 0),
        raw_suffix=raw_suffix,
        role_suffix=role_suffix,
        artifacts_dir=artifacts_dir,
        appears_as_agent=True,
    )
    if response_content is not None:
        agent.get_response_content = lambda: response_content  # type: ignore[method-assign]
    else:
        agent.get_response_content = lambda: None  # type: ignore[method-assign]
    agent.get_timestamped_reply_chunks = lambda: None  # type: ignore[method-assign]
    agent.get_live_reply_content = lambda: None  # type: ignore[method-assign]
    return agent


def _make_followup_agent(
    *,
    parent_timestamp: str,
    role_suffix: str,
    status: str = "DONE",
    response_content: str | None = None,
    live_reply: str | None = None,
    start_time_minute: int = 5,
) -> Agent:
    """Create a follow-up child agent (planner round or coder)."""
    from datetime import datetime

    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test_cl",
        project_file="/tmp/test.gp",
        status=status,
        start_time=datetime(2026, 3, 30, 12, start_time_minute, 0),
        parent_timestamp=parent_timestamp,
        role_suffix=role_suffix,
    )
    if response_content is not None:
        agent.get_response_content = lambda: response_content  # type: ignore[method-assign]
    else:
        agent.get_response_content = lambda: None  # type: ignore[method-assign]
    agent.get_timestamped_reply_chunks = lambda: None  # type: ignore[method-assign]
    if live_reply is not None:
        agent.get_live_reply_content = lambda: live_reply  # type: ignore[method-assign]
    else:
        agent.get_live_reply_content = lambda: None  # type: ignore[method-assign]
    return agent


def _rendered_text(mock_update: Any) -> str:
    """Extract all text content from a mock update call (handles Group and Text)."""
    from rich.console import Group
    from rich.syntax import Syntax

    def _to_str(r: Any) -> str:
        if isinstance(r, Syntax):
            return r.code
        return str(r)

    rendered = mock_update.call_args[0][0]
    if isinstance(rendered, Group):
        return "\n".join(_to_str(r) for r in rendered.renderables)
    return _to_str(rendered)


def test_main_plan_entry_aggregates_planner_and_coder_replies(
    tmp_path: Path,
) -> None:
    """Main .plan entry shows aggregated planner rounds and coder reply."""
    prompt_file = tmp_path / "workflow-plan_prompt.md"
    prompt_file.write_text("plan prompt")

    parent = _make_plan_agent(
        artifacts_dir=str(tmp_path), response_content="planner response"
    )
    followup_2 = _make_followup_agent(
        parent_timestamp="20260330120000",
        role_suffix=".2",
        response_content="feedback round 2",
        start_time_minute=5,
    )
    followup_code = _make_followup_agent(
        parent_timestamp="20260330120000",
        role_suffix=".code",
        response_content="coder response",
        start_time_minute=10,
    )

    panel = AgentPromptPanel.__new__(AgentPromptPanel)

    with (
        patch.object(panel, "update") as mock_update,
        patch.object(
            panel,
            "_collect_related_agents",
            return_value=[followup_2, followup_code],
        ),
    ):
        panel.update_display(parent)

        assert mock_update.called
        rendered_str = _rendered_text(mock_update)
        # Main reply present
        assert "planner response" in rendered_str
        # Follow-up planner round present
        assert "feedback round 2" in rendered_str
        assert "Planner (.2)" in rendered_str
        # Coder present
        assert "coder response" in rendered_str
        assert "Coder (.code)" in rendered_str


def test_nested_step_does_not_aggregate_followup_replies(
    tmp_path: Path,
) -> None:
    """Workflow child step should NOT aggregate follow-up replies."""
    prompt_file = tmp_path / "workflow-olcr-main_prompt.md"
    prompt_file.write_text("step prompt")

    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=None,
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="main",
        role_suffix=".plan",
        raw_suffix="20260330120000",
    )
    agent.get_response_content = lambda: "step response"  # type: ignore[method-assign]
    agent.get_timestamped_reply_chunks = lambda: None  # type: ignore[method-assign]

    panel = AgentPromptPanel.__new__(AgentPromptPanel)

    with patch.object(panel, "update") as mock_update:
        panel.update_display(agent)

        assert mock_update.called
        rendered_str = _rendered_text(mock_update)
        assert "step response" in rendered_str
        # No aggregated sub-sections should appear
        assert "Planner (" not in rendered_str
        assert "Coder (" not in rendered_str


def test_non_plan_top_level_agent_does_not_aggregate(
    tmp_path: Path,
) -> None:
    """Top-level agent without .plan role_suffix should NOT aggregate."""
    prompt_file = tmp_path / "workflow-run_prompt.md"
    prompt_file.write_text("run prompt")

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=None,
        artifacts_dir=str(tmp_path),
        raw_suffix="20260330120000",
        role_suffix=None,
    )
    agent.get_response_content = lambda: "agent response"  # type: ignore[method-assign]
    agent.get_timestamped_reply_chunks = lambda: None  # type: ignore[method-assign]

    panel = AgentPromptPanel.__new__(AgentPromptPanel)

    with patch.object(panel, "update") as mock_update:
        panel.update_display(agent)

        assert mock_update.called
        rendered_str = _rendered_text(mock_update)
        assert "agent response" in rendered_str
        assert "Planner (" not in rendered_str
        assert "Coder (" not in rendered_str


def test_aggregation_uses_agents_with_children_when_available(
    tmp_path: Path,
) -> None:
    """Aggregation should find related agents from _agents_with_children even if folded."""
    prompt_file = tmp_path / "workflow-plan_prompt.md"
    prompt_file.write_text("plan prompt")

    parent = _make_plan_agent(
        artifacts_dir=str(tmp_path), response_content="plan reply"
    )
    followup_code = _make_followup_agent(
        parent_timestamp="20260330120000",
        role_suffix=".code",
        response_content="coder output",
    )

    # Test _collect_related_agents directly to verify it prefers _agents_with_children
    panel = AgentPromptPanel.__new__(AgentPromptPanel)
    mock_app = type(
        "MockApp",
        (),
        {
            "_agents_with_children": [parent, followup_code],
            "_agents": [parent],  # folded: only parent visible
        },
    )()

    with patch.object(
        type(panel), "app", new_callable=lambda: property(lambda _self: mock_app)
    ):
        related = panel._collect_related_agents(parent)
        assert len(related) == 1
        assert related[0] is followup_code

    # Also verify the full rendering picks up the coder reply
    with (
        patch.object(panel, "update") as mock_update,
        patch.object(
            panel,
            "_collect_related_agents",
            return_value=[followup_code],
        ),
    ):
        panel.update_display(parent)

        assert mock_update.called
        rendered_str = _rendered_text(mock_update)
        assert "plan reply" in rendered_str
        assert "coder output" in rendered_str
        assert "Coder (.code)" in rendered_str
