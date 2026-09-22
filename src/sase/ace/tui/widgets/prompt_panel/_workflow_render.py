"""Rich renderable construction for workflow detail display."""

from collections.abc import Callable
from datetime import datetime as DateTime

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text

from sase.agent.status_buckets import (
    FEEDBACK_STATUS,
    PENDING_EPIC_STATUS,
    PENDING_TALE_STATUS,
    PLAN_APPROVED_STATUS,
    TALE_APPROVED_STATUS,
    WORKING_PLAN_STATUS,
    WORKING_TALE_STATUS,
)
from sase.project_display_names import humanize_cl_name, humanize_vcs_refs_in_text

from ...models.agent import Agent
from ...llm_calls import SlowToolSource
from ...llm_calls._constants import SLOW_TOOL_CALL_THRESHOLD_MS
from ...util.lazy_syntax import lazy_renderable
from ._agent_display_header_renderable import AgentHeaderRenderable
from ._helpers import (
    WORKFLOW_VARIABLES_SECTION_LABEL,
    append_model_field,
    append_section_heading,
    project_display_label,
)
from ._identity_header import IdentityHeader, WORKFLOW_IDENTITY_COLOR
from ._workflow_steps import format_workflow_steps_rich
from ._workflow_types import WorkflowDetailSnapshot

WORKFLOW_STATUS_STYLES: dict[str, str] = {
    "RUNNING": "#87D7FF",
    "QUEUED": "#5F87FF",
    "WAITING": "#AF87FF",
    "WAITING INPUT": "#FFAF5F",
    "DONE": "#5FD75F",
    "FAILED": "#FF5F5F",
    "PLAN": "#FF87AF",
    PENDING_TALE_STATUS: "#FF87AF",
    PENDING_EPIC_STATUS: "#D787FF",
    FEEDBACK_STATUS: "#FF5FD7",
    PLAN_APPROVED_STATUS: "#00D7AF",
    TALE_APPROVED_STATUS: "#00D7D7",
    WORKING_PLAN_STATUS: "#00AF87",
    WORKING_TALE_STATUS: "#00AFAF",
    "PLAN REJECTED": "#D7AF5F",
    "EPIC CREATED": "#5FD7AF",
    "QUESTION": "#FFAF00",
    "ANSWERED": "#5FD7FF",
}


def build_workflow_detail_renderable(
    agent: Agent,
    snapshot: WorkflowDetailSnapshot,
    *,
    slow_tool_sources: tuple[SlowToolSource, ...] | None = None,
    slow_tool_call_threshold_ms: int = SLOW_TOOL_CALL_THRESHOLD_MS,
    render_prompt: Callable[[str], RenderableType] | None = None,
    detach_identity: bool = False,
) -> Group:
    """Build the rich workflow-detail renderable from an existing snapshot."""
    header_text = Text()
    identity_text = Text()
    if detach_identity:
        fields_text = identity_text
    else:
        fields_text = header_text
        # Header - WORKFLOW DETAILS
        append_section_heading(header_text, "WORKFLOW DETAILS")

    # Workflow name (stored in workflow field)
    fields_text.append("Workflow: ", style="bold #87D7FF")
    fields_text.append(f"{agent.workflow or 'unknown'}\n", style="#AF87D7 bold")

    # Extract meta_* overrides from step outputs
    meta_project = None
    meta_patch = None
    meta_workspace = None
    meta_fields_data = snapshot.meta_raw
    if meta_fields_data:
        meta_project = meta_fields_data.get("meta_project")
        meta_patch = meta_fields_data.get("meta_patch")
        meta_workspace = meta_fields_data.get("meta_workspace")

    # Project/Patch with meta_* priority
    if meta_project:
        fields_text.append("Project: ", style="bold #87D7FF")
        fields_text.append(
            f"{project_display_label(agent, meta_project)}\n", style="#00D7AF"
        )
    elif meta_patch:
        fields_text.append("Patch: ", style="bold #87D7FF")
        fields_text.append(f"{humanize_cl_name(str(meta_patch))}\n", style="#00D7AF")
    else:
        fields_text.append("Patch: ", style="bold #87D7FF")
        fields_text.append(f"{humanize_cl_name(agent.cl_name)}\n", style="#00D7AF")

    # Workspace (if available) - check meta_workspace first, then agent field
    workspace_num = meta_workspace or agent.workspace_num
    if workspace_num is not None:
        fields_text.append("Workspace: ", style="bold #87D7FF")
        fields_text.append(f"#{workspace_num}\n", style="#5FD7FF")

    # Model (with provider-themed styling)
    append_model_field(
        fields_text,
        agent.model,
        agent.llm_provider,
        agent.reasoning_effort,
        agent.model_alias,
    )

    # VCS provider
    if agent.vcs_provider:
        fields_text.append("VCS: ", style="bold #87D7FF")
        fields_text.append(f"{agent.vcs_provider}\n", style="#5FD7AF")

    # Status
    fields_text.append("Status: ", style="bold #87D7FF")
    status_style = WORKFLOW_STATUS_STYLES.get(agent.status, "#D7D7FF")
    fields_text.append(f"{agent.status}\n", style=status_style)
    if agent.activity:
        fields_text.append("Activity: ", style="bold #87D7FF")
        fields_text.append(f"{agent.activity}\n", style="bold #D7AF5F")

    # Timestamp(s)
    fields_text.append("Timestamps: ", style="bold #87D7FF")
    fields_text.append(f"{agent.timestamps_display}\n", style="#D7D7FF")

    # PID (if available)
    if agent.pid:
        fields_text.append("PID: ", style="bold #87D7FF")
        fields_text.append(f"{agent.pid}\n", style="#FF87D7 bold")

    if detach_identity:
        body_text = Text()
    else:
        body_text = header_text

    # Failed workflows always expose an ERROR section and raw-output breadcrumb.
    is_failed = agent.display_status == "FAILED"
    if agent.error_message or is_failed:
        body_text.append("\n")
        append_section_heading(
            body_text,
            "ERROR",
            style="bold #FF5F5F underline",
            section_id="error",
        )
        error_message = agent.error_message or "Runner failed without error details."
        body_text.append(f"{error_message}\n", style="bold #FF5F5F")
    if agent.output_path and is_failed:
        body_text.append("Output: ", style="bold #87D7FF")
        body_text.append(f"{agent.output_path}\n", style="dim")

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
        body_text.append("\n")
        append_section_heading(
            body_text,
            WORKFLOW_VARIABLES_SECTION_LABEL,
        )
        for name, value in meta_fields:
            body_text.append(f"{name}: ", style="bold #87D7FF")
            body_text.append(f"{value}\n", style="#5FD75F")

    # Inputs (if available)
    inputs = snapshot.inputs
    if inputs:
        body_text.append("\n")
        append_section_heading(body_text, "INPUTS")
        for key, value in inputs.items():
            body_text.append(f"  {key}: ", style="bold #87D7FF")
            if isinstance(value, str):
                body_text.append(f'"{value}"\n', style="#5FD75F")
            else:
                body_text.append(f"{value}\n", style="#5FD75F")

    if slow_tool_sources is not None:
        from ._agent_slow_tools import (
            append_slow_tool_calls_section_no_fold_owner,
        )

        append_slow_tool_calls_section_no_fold_owner(
            body_text,
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
    renderables: list[RenderableType]
    if detach_identity:
        from ._identity_header_compact import build_workflow_compact_lines

        identity = IdentityHeader(
            kind_label="WORKFLOW",
            accent=WORKFLOW_IDENTITY_COLOR,
            expanded=identity_text,
            compact=build_workflow_compact_lines(agent=agent),
            has_hints=False,
        )
        renderables = [AgentHeaderRenderable(body_text, (), identity_header=identity)]
    else:
        renderables = [header_text]
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
        prompt_header = Text()
        prompt_header.append("\n")
        prompt_header.append("─" * 50 + "\n", style="dim")
        prompt_header.append("\n")
        append_section_heading(prompt_header, "AGENT PROMPT")
        renderables.append(prompt_header)
        if render_prompt is not None:
            renderables.append(render_prompt(prompt_content))
        else:
            prompt_content = humanize_vcs_refs_in_text(prompt_content)
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
