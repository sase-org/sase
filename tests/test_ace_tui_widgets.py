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
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.commits_builder import _should_show_commits_drawers
from sase.ace.tui.widgets.prompt_panel import (
    AgentPromptPanel,
    load_xprompts_used,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_detail_header_summary,
    build_header_text,
    cache_detail_header_summary,
    get_prompt_content,
)
from sase.ace.tui.widgets.prompt_panel._agent_xprompts import (
    _COLOR_HEADER,
    _COLOR_PART,
    _COLOR_WORKFLOW,
)
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_rendered_section_is_compact,
)


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


def test_tab_bar_changespec_tab_label_is_artifacts() -> None:
    tab_bar = TabBar()
    plain = tab_bar._build_content().plain
    assert " Artifacts " in plain
    assert " PRs " not in plain
    assert " ChangeSpecs " not in plain


def test_tab_bar_label_order_is_agents_artifacts_axe() -> None:
    tab_bar = TabBar()
    plain = tab_bar._build_content().plain
    assert plain.index("Agents") < plain.index("Artifacts") < plain.index("AXE")


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
) -> Agent:
    """Create a minimal Agent for prompt panel testing."""
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        artifacts_dir=artifacts_dir,
        parent_workflow=parent_workflow,
        step_name=step_name,
        step_type=step_type,
        step_output=step_output,
        activity=activity,
    )


def test_agent_row_omits_live_pdf_activity_suffix() -> None:
    agent = _make_agent(activity="PDF 3/3 docs/notes.md")

    _left, suffix, _option_id = format_agent_option(
        agent,
        0,
        is_selected=False,
    )

    assert "PDF" not in suffix.plain


def test_agent_detail_header_displays_live_pdf_activity() -> None:
    agent = _make_agent(activity="PDF 3/3 docs/notes.md")

    header, _ = build_header_text(agent)

    assert "Activity: PDF 3/3 docs/notes.md" in header.plain


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
        assert_rendered_section_is_compact(
            rendered,
            "STEP OUTPUT",
            "parallel output data",
        )


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
        assert_rendered_section_is_compact(
            rendered,
            "STEP OUTPUT",
            "No output available.",
        )


def test_bash_and_python_step_sections_are_compact() -> None:
    cases = (
        ("bash", "BASH COMMAND", "echo compact", {"_data": "done"}, "echo"),
        ("python", "PYTHON CODE", None, None, "No source available."),
    )
    for step_type, source_heading, source, output, first_source in cases:
        agent = _make_agent(
            parent_workflow="demo",
            step_name=f"{step_type}-step",
            step_type=step_type,
            step_output=output,
        )
        agent.step_source = source
        panel = AgentPromptPanel.__new__(AgentPromptPanel)

        with patch.object(panel, "update") as mock_update:
            panel.update_display(agent)

        rendered = mock_update.call_args.args[0]
        assert_rendered_section_is_compact(
            rendered,
            source_heading,
            first_source,
        )
        assert_rendered_section_is_compact(
            rendered,
            "STEP OUTPUT",
            "done" if output else "No output available.",
        )


async def test_update_display_expands_prompt_for_done_workflow_without_diff() -> None:
    """Done top-level workflow (non-agent) without diff_path should expand prompt, not tools."""
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
            project_file="/tmp/test.sase",
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
        tools_scroll = detail.query_one("#agent-tools-scroll")
        prompt_scroll = detail.query_one("#agent-prompt-scroll")
        assert diff_scroll.has_class("hidden")
        assert tools_scroll.has_class("hidden")
        assert prompt_scroll.has_class("expanded")
        assert not detail.is_tools_visible()


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

            # Press TAB to switch to axe (PRs -> AXE in the new order)
            await page.press("tab")
            await page.expect_state("tab", "axe")

            # Press TAB to switch to agents
            await page.press("tab")
            await page.expect_state("tab", "agents")

            # Press TAB to cycle back to changespecs
            await page.press("tab")
            await page.expect_state("tab", "changespecs")


# --- Xprompts Metadata Tests ---


def testload_xprompts_used_empty(tmp_path: Path) -> None:
    """No xprompts.json file returns None."""
    agent = _make_agent(artifacts_dir=str(tmp_path))
    result = load_xprompts_used(agent)

    assert result is None


def testload_xprompts_used_no_artifacts_dir() -> None:
    """Agent with no artifacts_dir returns None."""
    agent = _make_agent(artifacts_dir=None)
    result = load_xprompts_used(agent)

    assert result is None


def test_load_xprompts_used_child_step_does_not_fall_back_to_shared(
    tmp_path: Path,
) -> None:
    """A child step with no step file must not read the shared xprompts.json.

    The shared file holds launch/root metadata; a workflow-child row whose own
    step captured no xprompt usage shows nothing rather than the root's data.
    """
    (tmp_path / "xprompts.json").write_text(
        json.dumps(
            [
                {
                    "name": "plan",
                    "kind": "part",
                    "positional": [],
                    "named": {},
                    "tags": [],
                }
            ]
        )
    )

    agent = _make_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="build",
    )

    assert load_xprompts_used(agent) is None


def test_load_xprompts_used_root_reads_shared(tmp_path: Path) -> None:
    """A non-step (root) agent reads the shared xprompts.json."""
    records = [
        {
            "name": "plan",
            "kind": "part",
            "positional": [],
            "named": {},
            "tags": [],
        }
    ]
    (tmp_path / "xprompts.json").write_text(json.dumps(records))

    agent = _make_agent(artifacts_dir=str(tmp_path))

    assert load_xprompts_used(agent) == records


def test_xprompts_displayed_from_header_summary(tmp_path: Path) -> None:
    """Precomputed header summaries can render xprompt metadata."""
    metadata = [
        {
            "name": "propose",
            "kind": "workflow",
            "positional": [],
            "named": {"note": "blah"},
            "tags": [],
        },
        {
            "name": "cl",
            "kind": "workflow",
            "positional": [],
            "named": {},
            "tags": [],
        },
        {
            "name": "review_checklist",
            "kind": "part",
            "positional": [],
            "named": {},
            "tags": [],
        },
    ]
    metadata_file = tmp_path / "xprompts_main.json"
    metadata_file.write_text(json.dumps(metadata))

    agent = _make_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="main",
    )

    header, _ = build_header_text(
        agent,
        summary=build_detail_header_summary(agent),
    )

    assert "Xprompts: 2 workflows · 1 part" in header.plain
    assert "⌘ #propose  note=blah" in header.plain
    assert "⌘ #cl" in header.plain
    assert "▣ #review_checklist" in header.plain


def test_xprompt_part_value_uses_distinct_style(tmp_path: Path) -> None:
    """Part values render in a distinct color, not the metadata-label blue."""
    metadata = [
        {
            "name": "propose",
            "kind": "workflow",
            "positional": [],
            "named": {},
            "tags": [],
        },
        {
            "name": "review_checklist",
            "kind": "part",
            "positional": [],
            "named": {},
            "tags": [],
        },
    ]
    metadata_file = tmp_path / "xprompts_main.json"
    metadata_file.write_text(json.dumps(metadata))

    agent = _make_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="main",
    )

    header, _ = build_header_text(
        agent,
        summary=build_detail_header_summary(agent),
    )

    def styles_over(substring: str) -> set[str]:
        start = header.plain.index(substring)
        end = start + len(substring)
        return {
            str(span.style)
            for span in header.spans
            if span.start < end and span.end > start
        }

    assert _COLOR_HEADER in styles_over("Xprompts:")
    assert _COLOR_WORKFLOW in styles_over("#propose")
    assert _COLOR_PART in styles_over("#review_checklist")
    # The part value must not read like a metadata field label.
    assert _COLOR_PART != _COLOR_HEADER
    assert _COLOR_HEADER not in styles_over("#review_checklist")


def test_update_display_renders_xprompts_after_detail_settles(
    tmp_path: Path,
) -> None:
    """Full prompt updates render precomputed xprompt metadata."""
    metadata_file = tmp_path / "xprompts_main.json"
    metadata_file.write_text(
        json.dumps(
            [
                {
                    "name": "propose",
                    "kind": "workflow",
                    "positional": [],
                    "named": {},
                    "tags": [],
                }
            ]
        )
    )

    agent = _make_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="main",
    )
    panel = AgentPromptPanel.__new__(AgentPromptPanel)

    with patch.object(panel, "update") as mock_update:
        panel.update_display(agent)
        rendered = mock_update.call_args[0][0]
        assert "Xprompts: 1 workflow" not in str(rendered)

        cache_detail_header_summary(panel, agent, build_detail_header_summary(agent))
        panel.update_display(agent)

    assert mock_update.called
    rendered = mock_update.call_args[0][0]
    assert "Xprompts: 1 workflow" in str(rendered)
    assert "⌘ #propose" in str(rendered)
