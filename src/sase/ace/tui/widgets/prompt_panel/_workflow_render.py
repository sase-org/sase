"""Rich renderable construction for workflow detail display."""

from datetime import datetime as DateTime

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text

from sase.agent.status_buckets import (
    FEEDBACK_STATUS,
    PLAN_APPROVED_STATUS,
    TALE_APPROVED_STATUS,
    WORKING_PLAN_STATUS,
    WORKING_TALE_STATUS,
)
from sase.project_display_names import humanize_cl_name, humanize_vcs_refs_in_text

from ...models.agent import Agent
from ...tools import SlowToolSource
from ...tools._constants import SLOW_TOOL_CALL_THRESHOLD_MS
from ...util.lazy_syntax import lazy_renderable
from ._helpers import (
    WORKFLOW_VARIABLES_SECTION_LABEL,
    append_model_field,
    append_section_heading,
    project_display_label,
)
from ._workflow_steps import format_workflow_steps_rich
from ._workflow_types import WorkflowDetailSnapshot


def build_workflow_detail_renderable(
    agent: Agent,
    snapshot: WorkflowDetailSnapshot,
    *,
    slow_tool_sources: tuple[SlowToolSource, ...] | None = None,
    slow_tool_call_threshold_ms: int = SLOW_TOOL_CALL_THRESHOLD_MS,
) -> Group:
    """Build the rich workflow-detail renderable from an existing snapshot."""
    header_text = Text()

    # Header - WORKFLOW DETAILS
    append_section_heading(header_text, "WORKFLOW DETAILS")

    # Workflow name (stored in workflow field)
    header_text.append("Workflow: ", style="bold #87D7FF")
    header_text.append(f"{agent.workflow or 'unknown'}\n", style="#AF87D7 bold")

    # Extract meta_* overrides from step outputs
    meta_project = None
    meta_changespec = None
    meta_workspace = None
    meta_fields_data = snapshot.meta_raw
    if meta_fields_data:
        meta_project = meta_fields_data.get("meta_project")
        meta_changespec = meta_fields_data.get("meta_changespec")
        meta_workspace = meta_fields_data.get("meta_workspace")

    # Project/ChangeSpec with meta_* priority
    if meta_project:
        header_text.append("Project: ", style="bold #87D7FF")
        header_text.append(
            f"{project_display_label(agent, meta_project)}\n", style="#00D7AF"
        )
    elif meta_changespec:
        header_text.append("ChangeSpec: ", style="bold #87D7FF")
        header_text.append(
            f"{humanize_cl_name(str(meta_changespec))}\n", style="#00D7AF"
        )
    else:
        header_text.append("ChangeSpec: ", style="bold #87D7FF")
        header_text.append(f"{humanize_cl_name(agent.cl_name)}\n", style="#00D7AF")

    # Workspace (if available) - check meta_workspace first, then agent field
    workspace_num = meta_workspace or agent.workspace_num
    if workspace_num is not None:
        header_text.append("Workspace: ", style="bold #87D7FF")
        header_text.append(f"#{workspace_num}\n", style="#5FD7FF")

    # Model (with provider-themed styling)
    append_model_field(
        header_text, agent.model, agent.llm_provider, agent.reasoning_effort
    )

    # VCS provider
    if agent.vcs_provider:
        header_text.append("VCS: ", style="bold #87D7FF")
        header_text.append(f"{agent.vcs_provider}\n", style="#5FD7AF")

    # Status
    header_text.append("Status: ", style="bold #87D7FF")
    status_style = {
        "RUNNING": "#87D7FF",
        "WAITING": "#FF87D7",
        "WAITING INPUT": "#FFAF5F",
        "DONE": "#5FD75F",
        "FAILED": "#FF5F5F",
        "PLAN": "#FF87AF",
        FEEDBACK_STATUS: "#FF5FD7",
        PLAN_APPROVED_STATUS: "#00D7AF",
        TALE_APPROVED_STATUS: "#00D7D7",
        WORKING_PLAN_STATUS: "#00AF87",
        WORKING_TALE_STATUS: "#00AFAF",
        "PLAN REJECTED": "#D7AF5F",
        "EPIC CREATED": "#5FD7AF",
        "QUESTION": "#FFAF00",
        "ANSWERED": "#5FD7FF",
    }.get(agent.status, "#D7D7FF")
    header_text.append(f"{agent.status}\n", style=status_style)
    if agent.activity:
        header_text.append("Activity: ", style="bold #87D7FF")
        header_text.append(f"{agent.activity}\n", style="bold #D7AF5F")

    # Timestamp(s)
    header_text.append("Timestamps: ", style="bold #87D7FF")
    header_text.append(f"{agent.timestamps_display}\n", style="#D7D7FF")

    # PID (if available)
    if agent.pid:
        header_text.append("PID: ", style="bold #87D7FF")
        header_text.append(f"{agent.pid}\n", style="#FF87D7 bold")

    # Failed workflows always expose an ERROR section and raw-output breadcrumb.
    is_failed = agent.display_status == "FAILED"
    if agent.error_message or is_failed:
        header_text.append("\n")
        header_text.append("ERROR\n", style="bold #FF5F5F underline")
        error_message = agent.error_message or "Runner failed without error details."
        header_text.append(f"{error_message}\n", style="bold #FF5F5F")
    if agent.output_path and is_failed:
        header_text.append("Output: ", style="bold #87D7FF")
        header_text.append(f"{agent.output_path}\n", style="dim")

    # Compute traceback renderable for ERROR section
    error_tb_syntax: Syntax | None = None
    if agent.error_traceback:
        error_tb_syntax = Syntax(
            agent.error_traceback,
            "pytb",
            theme="monokai",
            word_wrap=True,
        )

    # Meta fields aggregated from all step outputs
    meta_fields = snapshot.meta_fields
    if meta_fields:
        header_text.append("\n")
        append_section_heading(
            header_text,
            WORKFLOW_VARIABLES_SECTION_LABEL,
        )
        for name, value in meta_fields:
            header_text.append(f"{name}: ", style="bold #87D7FF")
            header_text.append(f"{value}\n", style="#5FD75F")

    # Inputs (if available)
    inputs = snapshot.inputs
    if inputs:
        header_text.append("\n")
        append_section_heading(header_text, "INPUTS")
        for key, value in inputs.items():
            header_text.append(f"  {key}: ", style="bold #87D7FF")
            if isinstance(value, str):
                header_text.append(f'"{value}"\n', style="#5FD75F")
            else:
                header_text.append(f"{value}\n", style="#5FD75F")

    if slow_tool_sources is not None:
        from ._agent_slow_tools import append_slow_tool_calls_section

        append_slow_tool_calls_section(
            header_text,
            sources=slow_tool_sources,
            agent=agent,
            now=DateTime.now(),
            threshold_ms=slow_tool_call_threshold_ms,
        )

    # Separator + WORKFLOW STEPS header
    steps_header = Text()
    steps_header.append("\n")
    steps_header.append("─" * 50 + "\n", style="dim")
    steps_header.append("\n")
    append_section_heading(steps_header, "WORKFLOW STEPS")

    # Load and format workflow steps from workflow_state.json
    steps_rich = workflow_steps_rich_from_snapshot(snapshot)
    renderables: list[RenderableType] = [header_text]
    if error_tb_syntax:
        renderables.append(error_tb_syntax)
    renderables.append(steps_header)
    if steps_rich:
        renderables.append(steps_rich)
    else:
        steps_header.append("No workflow state found.\n", style="dim italic")

    # AGENT PROMPT section - show the prompt that was attempted
    prompt_content = snapshot.prompt_content
    if prompt_content:
        prompt_content = humanize_vcs_refs_in_text(prompt_content)
        prompt_header = Text()
        prompt_header.append("\n")
        prompt_header.append("─" * 50 + "\n", style="dim")
        prompt_header.append("\n")
        append_section_heading(prompt_header, "AGENT PROMPT")
        renderables.append(prompt_header)
        renderables.append(lazy_renderable(prompt_content, "markdown"))

    return Group(*renderables)


def workflow_steps_rich_from_snapshot(
    snapshot: WorkflowDetailSnapshot,
) -> Text | None:
    """Build a rich step-list renderable from an existing snapshot."""
    steps = snapshot.steps
    if not steps:
        if snapshot.error:
            text = Text()
            text.append("Error: ", style="bold #FF5F5F")
            text.append(f"{snapshot.error}\n", style="#FF5F5F")
            if snapshot.traceback:
                text.append("\nTraceback:\n", style="bold #FF5F5F")
                text.append(f"{snapshot.traceback}\n", style="dim")
            return text
        return None

    return format_workflow_steps_rich(
        steps, snapshot.embedded_markers, snapshot.embedded_meta
    )
