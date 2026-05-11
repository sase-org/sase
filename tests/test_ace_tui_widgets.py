"""Tests for the ace TUI widgets (section builders and TabBar)."""

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.changespec import CommitEntry
from sase.ace.testing import AcePage, make_changespec
from sase.ace.tui import AceApp
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import ChangeSpecInfoPanel, TabBar
from sase.ace.tui.widgets.tab_bar import TabName
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.commits_builder import _should_show_commits_drawers
from sase.ace.tui.widgets.prompt_panel import (
    AgentPromptPanel,
    load_embedded_workflows,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import get_prompt_content


# --- _should_show_commits_drawers Tests ---


def test_should_show_commits_drawers_expanded() -> None:
    """All entries show drawers when expanded."""
    entry = CommitEntry(number=5, note="test")
    changespec = make_changespec(
        commits=[
            CommitEntry(number=1, note="first"),
            CommitEntry(number=5, note="test"),
        ]
    )

    assert _should_show_commits_drawers(entry, changespec, FoldLevel.EXPANDED)


def test_should_show_commits_drawers_collapsed_intermediate_hidden() -> None:
    """Intermediate entries hide drawers when collapsed."""
    entry = CommitEntry(number=3, note="intermediate")
    changespec = make_changespec(
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
    changespec = make_changespec(
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
    changespec = make_changespec(
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


def _agents_span_style(tab_bar: TabBar) -> str:
    """Return the style string applied to the Agents label span."""
    content = tab_bar._build_content()
    start, end = tab_bar._tab_ranges["agents"]
    for span in content.spans:
        if span.start == start and span.end == end:
            return str(span.style)
    raise AssertionError("Agents tab span not found in rendered content")


def test_tab_bar_inactive_agents_badge_renders_count_and_alert_style() -> None:
    """Inactive Agents tab with a positive count shows Agents(N) in yellow."""
    tab_bar = TabBar()
    tab_bar.update_tab("changespecs")
    tab_bar.set_tab_badge("agents", 2)

    content = tab_bar._build_content()
    assert "Agents(2)" in content.plain
    assert "Agents(2 )" not in content.plain
    assert " Agents(2)" in content.plain  # leading padding space
    assert _agents_span_style(tab_bar) == "bold #FFAF00"


def test_tab_bar_active_agents_suppresses_badge() -> None:
    """Active Agents tab keeps its normal active style and hides the count."""
    tab_bar = TabBar()
    tab_bar.set_tab_badge("agents", 2)
    tab_bar.update_tab("agents")

    content = tab_bar._build_content()
    assert "Agents(2)" not in content.plain
    assert " Agents " in content.plain
    assert _agents_span_style(tab_bar) == "bold #87D7FF"


def test_tab_bar_zero_badge_restores_plain_label() -> None:
    """Setting the badge back to zero restores the inactive plain label."""
    tab_bar = TabBar()
    tab_bar.update_tab("changespecs")
    tab_bar.set_tab_badge("agents", 3)
    tab_bar.set_tab_badge("agents", 0)

    content = tab_bar._build_content()
    assert "Agents(" not in content.plain
    assert " Agents " in content.plain
    assert _agents_span_style(tab_bar) == "#888888"


def test_tab_bar_click_range_still_identifies_agents_with_badge() -> None:
    """Click ranges cover the badge-augmented Agents label."""
    tab_bar = TabBar()
    tab_bar.update_tab("changespecs")
    tab_bar.set_tab_badge("agents", 7)

    content = tab_bar._build_content()
    start, end = tab_bar._tab_ranges["agents"]
    assert content.plain[start:end] == " Agents(7) "

    # Each character position inside the range resolves to the agents tab.
    for x in range(start, end):
        hit: TabName | None = None
        for tab, (s, e) in tab_bar._tab_ranges.items():
            if s <= x < e:
                hit = tab
                break
        assert hit == "agents", f"position {x} did not resolve to agents tab"


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
    activity: str | None = None,
    pdf_status: dict[str, Any] | None = None,
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
        activity=activity,
        pdf_status=pdf_status,
    )


def test_agent_row_displays_active_pdf_status_suffix() -> None:
    agent = _make_agent(
        pdf_status={
            "stage": "engine_started",
            "index": 2,
            "total": 5,
            "source_path": "docs/notes.md",
            "active": True,
        },
    )

    _left, suffix, _option_id = format_agent_option(
        agent,
        0,
        is_selected=False,
    )

    assert "PDF 2/5 docs/notes.md" in suffix.plain


def test_agent_row_honors_explicit_pdf_activity_suffix() -> None:
    agent = _make_agent(
        activity="PDF done 2/5 docs/notes.md",
        pdf_status={
            "stage": "completed",
            "generated": 2,
            "total": 5,
            "active": False,
        },
    )

    _left, suffix, _option_id = format_agent_option(
        agent,
        0,
        is_selected=False,
    )

    assert "PDF done 2/5 docs/notes.md" in suffix.plain


def test_agent_row_omits_completed_pdf_status_suffix() -> None:
    agent = _make_agent(
        pdf_status={
            "stage": "completed",
            "generated": 4,
            "skipped": 1,
            "total": 5,
            "active": False,
        },
    )

    _left, suffix, _option_id = format_agent_option(
        agent,
        0,
        is_selected=False,
    )

    assert suffix.plain == ""
    assert "PDFs done" not in suffix.plain


def test_agent_row_omits_inactive_skipped_pdf_status_suffix() -> None:
    agent = _make_agent(
        pdf_status={
            "stage": "skipped",
            "reason": "over attachment limit",
            "active": False,
        },
    )

    _left, suffix, _option_id = format_agent_option(
        agent,
        0,
        is_selected=False,
    )

    assert suffix.plain == ""
    assert "PDFs skipped" not in suffix.plain


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

    result = get_prompt_content(agent)

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

    result = get_prompt_content(agent)

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
    changespecs = [make_changespec()]
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", changespecs=changespecs) as page:
            # Initial state - changespecs tab
            await page.expect_state("tab", "changespecs")

            # Press TAB to switch to agents
            await page.press("tab")
            await page.expect_state("tab", "agents")

            # Press TAB to switch to axe
            await page.press("tab")
            await page.expect_state("tab", "axe")

            # Press TAB to cycle back to changespecs
            await page.press("tab")
            await page.expect_state("tab", "changespecs")


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
