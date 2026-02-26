"""Tests for the ace TUI widgets (section builders and TabBar)."""

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.changespec import ChangeSpec, CommentEntry, CommitEntry, HookEntry
from sase.ace.tui import AceApp
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import TabBar
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
    """All entries show drawers when expanded (commits_collapsed=False)."""
    entry = CommitEntry(number=5, note="test")
    changespec = _make_changespec(
        commits=[
            CommitEntry(number=1, note="first"),
            CommitEntry(number=5, note="test"),
        ]
    )

    assert _should_show_commits_drawers(entry, changespec, commits_collapsed=False)


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

    assert not _should_show_commits_drawers(entry, changespec, commits_collapsed=True)


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

    assert not _should_show_commits_drawers(entry, changespec, commits_collapsed=True)


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

    assert _should_show_commits_drawers(entry_a, changespec, commits_collapsed=True)
    assert _should_show_commits_drawers(entry_b, changespec, commits_collapsed=True)


# --- TabBar Widget Tests ---


def test_tab_bar_update_tab_to_agents() -> None:
    """Test that update_tab changes the current tab to agents."""
    tab_bar = TabBar()
    tab_bar.update_tab("agents")
    assert tab_bar._current_tab == "agents"


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
