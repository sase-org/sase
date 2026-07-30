"""Tests for agent prompt-panel activity and workflow-step rendering."""

import time
from pathlib import Path
from unittest.mock import patch

from rich.console import Group
from textual.app import App, ComposeResult

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_header_text,
    get_prompt_content,
)
from tests.ace.tui.widgets._agent_display_helpers import make_workflow_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_rendered_section_is_compact,
)


def test_agent_row_omits_live_pdf_activity_suffix() -> None:
    agent = make_workflow_agent(activity="PDF 3/3 docs/notes.md")

    _left, suffix, _option_id = format_agent_option(
        agent,
        0,
        is_selected=False,
    )

    assert "PDF" not in suffix.plain


def test_agent_detail_header_displays_live_pdf_activity() -> None:
    agent = make_workflow_agent(activity="PDF 3/3 docs/notes.md")

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

    agent = make_workflow_agent(
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

    agent = make_workflow_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="research",
    )

    result = get_prompt_content(agent)

    # No step-specific match, so falls back to most recent (the only file)
    assert result == "api_research prompt"


def test_parallel_step_does_not_show_agent_prompt(tmp_path: Path) -> None:
    """Parallel workflow steps should show STEP OUTPUT, not AGENT PROMPT."""
    # Create a prompt file that would be found if parallel wasn't filtered
    prompt_file = tmp_path / "workflow-olcr-research_prompt.md"
    prompt_file.write_text("wrong prompt content")

    agent = make_workflow_agent(
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
    agent = make_workflow_agent(
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
        agent = make_workflow_agent(
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
