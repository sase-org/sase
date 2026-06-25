"""Header rendering for the agent prompt panel."""

from __future__ import annotations

from rich.syntax import Syntax
from rich.text import Text

from ...models.agent import Agent
from ...models.agent_bead import cached_bead_display
from .._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE
from ._agent_display_state import DetailHeaderSummary, HeaderHintState
from ._file_path_hints import append_text_with_file_hints
from ._helpers import (
    WORKFLOW_VARIABLES_SECTION_LABEL,
    append_model_field,
    extract_meta_fields,
    should_render_agent_detail_model,
)


_UNASSIGNED_AGENT_NAME_DISPLAY = "unassigned"


def _append_major_section_divider(text: Text) -> None:
    """Append the standard prompt-panel major-section divider."""
    text.append("\n")
    text.append("\u2500" * 50 + "\n", style="dim")
    text.append("\n")


def _append_output_variables_section(
    text: Text,
    output_variables: dict[str, str],
) -> None:
    if not output_variables:
        return

    _append_major_section_divider(text)
    text.append("OUTPUT VARIABLES\n", style="bold #D7AF5F underline")
    text.append("\n")
    for key in sorted(output_variables):
        value = output_variables[key]
        if "\n" not in value:
            text.append(f"{key}: ", style="bold #87D7FF")
            text.append(f"{value}\n", style="#5FD75F")
            continue

        text.append(f"{key}:\n", style="bold #87D7FF")
        for line in value.splitlines() or [""]:
            text.append("  ")
            text.append(f"{line}\n", style="#5FD75F")


def build_header_text(
    agent: Agent,
    *,
    cheap: bool = False,
    hint_state: HeaderHintState | None = None,
    summary: DetailHeaderSummary | None = None,
) -> tuple[Text, Syntax | None]:
    """Build the agent metadata section with trailing separator.

    Contains agent metadata (name, workspace, model, timestamps, etc.),
    error information, and a trailing separator line.

    Args:
        agent: The agent to render a header for.
        cheap: When True, skip any disk-touching enrichments (e.g. xprompt
            metadata loaded from disk). Used by the j/k immediate
            path so the header renders within one frame; the debounced full
            update fills in the omitted fields.
        hint_state: Optional mutable file-hint state. When provided, path-like
            timestamp details are rendered with selectable hint markers.
        summary: Optional precomputed/cached header enrichments. Expensive
            sections are rendered only from this object; the header builder
            does not do artifact listing, diff discovery, or bead lookup.

    Returns:
        Tuple of (header_text, error_traceback_syntax).
    """
    header_text = Text()

    # Agent name is always the first metadata row in the details panel.
    header_text.append("Name: ", style="bold #87D7FF")
    if agent.agent_name:
        header_text.append(f"{agent.agent_name}\n", style=_AGENT_NAME_ANNOTATION_STYLE)
        # Render ``Bead:`` only from confirmed cache state. The full path reads
        # the value precomputed onto ``summary`` (itself cache-derived); the
        # cheap/cold paths read the cache directly. None of these touch bead
        # storage, and an unconfirmed candidate renders nothing.
        if summary is not None:
            bead_display = summary.bead_display
        else:
            cached_display = cached_bead_display(agent)
            bead_display = cached_display if isinstance(cached_display, str) else None
        if bead_display:
            header_text.append("Bead: ", style="bold #87D7FF")
            header_text.append(f"{bead_display}\n", style="bold #FFAF00")
    else:
        header_text.append(f"{_UNASSIGNED_AGENT_NAME_DISPLAY}\n", style="dim")

    # Spawn-on-retry: render a retry-chain breadcrumb when the agent is
    # part of one (either a retry attempt or a parent that handed off).
    if agent.is_retry_attempt or agent.is_retried_parent:
        header_text.append("Retry chain: ", style="bold #87D7FF")
        header_text.append("↻ ", style="bold #FFAF00")
        if agent.is_retry_attempt:
            header_text.append(f"attempt #{agent.retry_attempt}", style="#FFAF00")
            if agent.retry_error_category:
                header_text.append(
                    f" ({agent.retry_error_category})", style="dim #FFAF00"
                )
        if agent.is_retried_parent:
            if agent.is_retry_attempt:
                header_text.append(", ", style="dim")
            header_text.append("handed off to retry", style="dim #FFAF00")
        header_text.append("\n")

    # Extract meta_* overrides from step_output
    step_output = agent.step_output if isinstance(agent.step_output, dict) else None
    meta_project = step_output.get("meta_project") if step_output is not None else None
    meta_changespec = (
        step_output.get("meta_changespec") if step_output is not None else None
    )
    meta_fields = extract_meta_fields(step_output) if step_output is not None else []

    # For workflow step agents, show "Step" instead of "ChangeSpec"
    if agent.is_workflow_child and agent.step_name:
        header_text.append("Step: ", style="bold #87D7FF")
        header_text.append(f"{agent.step_name}\n", style="#00D7AF")
    elif meta_changespec:
        header_text.append("ChangeSpec: ", style="bold #87D7FF")
        header_text.append(f"{meta_changespec}", style="#00D7AF")
        if agent.cl_num:
            header_text.append(" (")
            header_text.append(agent.cl_num, style="bold underline #569CD6")
            header_text.append(")")
        header_text.append("\n")
    elif meta_project:
        header_text.append("Project: ", style="bold #87D7FF")
        header_text.append(f"{meta_project}\n", style="#00D7AF")
    elif agent.is_project_agent:
        header_text.append("Project: ", style="bold #87D7FF")
        header_text.append(f"{agent.cl_name}\n", style="#00D7AF")
    else:
        # ChangeSpec name
        header_text.append("ChangeSpec: ", style="bold #87D7FF")
        header_text.append(f"{agent.cl_name}", style="#00D7AF")
        if agent.cl_num:
            header_text.append(" (")
            header_text.append(agent.cl_num, style="bold underline #569CD6")
            header_text.append(")")
        header_text.append("\n")

    # Workspace (if available)
    # Hide workspace for deferred-workspace agents (workspace_num=0 means
    # no workspace allocated yet, used by WAITING agents)
    workspace_num = agent.effective_workspace_num
    if workspace_num is not None and workspace_num > 0:
        header_text.append("Workspace: ", style="bold #87D7FF")
        header_text.append(f"#{workspace_num}\n", style="#5FD7FF")

    # Workflow (if available) -- only for multi-step workflows, not
    # appears-as-agent workflows (which are embedded, not standalone)
    if agent.workflow and not agent.appears_as_agent:
        header_text.append("Workflow: ", style="bold #87D7FF")
        header_text.append(f"{agent.workflow}\n")

    # Xprompts (if available) - only for agent/prompt steps.
    # Skipped on the cheap path: load_xprompts_used touches disk, and
    # the debounced full update will populate this field shortly after.
    if not cheap and summary is not None:
        from ._agent_xprompts import append_agent_xprompts_section

        append_agent_xprompts_section(header_text, summary.xprompts_used)

    # Model (with provider-themed styling)
    if should_render_agent_detail_model(agent):
        append_model_field(
            header_text, agent.model, agent.llm_provider, agent.reasoning_effort
        )

    # VCS provider
    if agent.vcs_provider:
        header_text.append("VCS: ", style="bold #87D7FF")
        header_text.append(f"{agent.vcs_provider}\n", style="#5FD7AF")

    # Mode (autonomous agents)
    if agent.approve:
        header_text.append("Mode: ", style="bold #87D7FF")
        if agent.auto_approve_plan_action == "epic":
            header_text.append("\u26a1 Epic Auto-Approve\n", style="bold #00FFFF")
        else:
            header_text.append("\u26a1 Auto-Approve\n", style="bold #00FFFF")

    # PID (if available)
    if agent.pid:
        header_text.append("PID: ", style="bold #87D7FF")
        header_text.append(f"{agent.pid}\n", style="#FF87D7 bold")

    # BUG field (if available)
    if agent.bug:
        header_text.append("BUG: ", style="bold #87D7FF")
        header_text.append(f"{agent.bug}\n", style="bold underline #569CD6")

    # Waiting info (when agent is waiting for dependencies, a duration, or absolute time)
    if agent.waiting_for or agent.wait_duration or agent.wait_until:
        from sase.ace.tui.models.agent import (
            format_compact_duration,
            format_wait_until,
            wait_until_target_and_reference,
        )

        header_text.append("Waiting for: ", style="bold #87D7FF")
        parts: list[str] = []
        if agent.waiting_for:
            parts.append(", ".join(agent.waiting_for))
        if agent.wait_until:
            target_label = format_wait_until(agent.wait_until)
            parts.append(f"until {target_label}")
        elif agent.wait_duration:
            parts.append(format_compact_duration(agent.wait_duration))
        header_text.append(" + ".join(parts), style="#FF87D7")
        # Show live countdown for absolute-time waits
        if agent.wait_until:
            target, reference = wait_until_target_and_reference(agent.wait_until)
            remaining = (target - reference).total_seconds()
            if remaining > 0:
                header_text.append(
                    f" ({format_compact_duration(remaining)} left)",
                    style="dim #AF87FF",
                )
        # Show live countdown for duration waits
        elif agent.wait_duration and agent.start_time:
            from datetime import datetime, timedelta

            target = agent.start_time + timedelta(seconds=agent.wait_duration)
            remaining = (target - datetime.now()).total_seconds()
            if remaining > 0:
                header_text.append(
                    f" ({format_compact_duration(remaining)} left)", style="dim #AF87FF"
                )
        header_text.append("\n")

    # Retry info (for agents that have retried or are using fallback)
    if agent.retry_count > 0 or agent.using_fallback or agent.attempt_history:
        header_text.append("Retries: ", style="bold #87D7FF")
        header_text.append(
            f"{agent.retry_count}/{agent.max_retries}\n", style="#FF8700"
        )
        for record in agent.attempt_history:
            try:
                hhmmss = record.start_hhmmss
            except (ValueError, OSError):
                hhmmss = "??:??:??"
            snippet = record.error_snippet or record.status
            fb_marker = " (fallback)" if record.used_fallback else ""
            header_text.append(
                f"  Attempt {record.attempt_number} · {hhmmss}{fb_marker} · "
                f"{record.status}: {snippet}\n",
                style="dim #FF8700",
            )
        if agent.fallback_model:
            header_text.append("Fallback: ", style="bold #87D7FF")
            if agent.using_fallback:
                header_text.append(f"{agent.fallback_model}\n", style="bold #FF8700")
            else:
                header_text.append(f"{agent.fallback_model}\n", style="dim #FF8700")

    # Timestamp(s)
    if agent.activity:
        header_text.append("Activity: ", style="bold #87D7FF")
        header_text.append(f"{agent.activity}\n", style="bold #D7AF5F")

    header_text.append("Timestamps: ", style="bold #87D7FF")
    if hint_state is None:
        header_text.append(f"{agent.timestamps_display}\n", style="#D7D7FF")
    else:
        hint_state.hint_counter = append_text_with_file_hints(
            header_text,
            f"{agent.timestamps_display}\n",
            hint_state.hint_counter,
            hint_state.hint_mappings,
            hint_state.workspace_dir,
            style="#D7D7FF",
        )

    _append_output_variables_section(header_text, agent.output_variables)

    from ._agent_commits import append_agent_commits_section

    append_agent_commits_section(header_text, agent)

    if not cheap and summary is not None:
        from ._agent_artifacts import append_agent_artifacts_section
        from ._agent_deltas import append_agent_deltas_section

        append_agent_deltas_section(
            header_text,
            delta_entries=summary.delta_entries,
            linked_delta_groups=summary.linked_delta_groups,
            hint_state=hint_state,
        )
        append_agent_artifacts_section(
            header_text,
            artifact_paths=summary.artifact_paths,
            hint_state=hint_state,
        )

    # Meta fields from step output
    if meta_fields:
        _append_major_section_divider(header_text)
        header_text.append(
            f"{WORKFLOW_VARIABLES_SECTION_LABEL}\n",
            style="bold #D7AF5F underline",
        )
        header_text.append("\n")
        for name, value in meta_fields:
            header_text.append(f"{name}: ", style="bold #87D7FF")
            header_text.append(f"{value}\n", style="#5FD75F")

    if (
        not cheap
        and summary is not None
        and (summary.memory_reads or summary.skill_uses or summary.opened_workspaces)
    ):
        from ._agent_context import append_agent_context_section

        append_agent_context_section(
            header_text,
            memory_reads=summary.memory_reads,
            skill_uses=summary.skill_uses,
            opened_workspaces=summary.opened_workspaces,
        )

    # Error message (for failed agents)
    if agent.error_message:
        header_text.append("\n")
        header_text.append("ERROR\n", style="bold #FF5F5F underline")
        header_text.append(f"{agent.error_message}\n", style="bold #FF5F5F")
        if agent.output_path:
            header_text.append("Output: ", style="bold #87D7FF")
            header_text.append(f"{agent.output_path}\n", style="dim")

    # Compute traceback renderable for ERROR section (included in all paths)
    error_tb_syntax: Syntax | None = None
    if agent.error_traceback:
        error_tb_syntax = Syntax(
            agent.error_traceback,
            "pytb",
            theme="monokai",
            word_wrap=True,
        )

    # Separator
    header_text.append("\n")
    header_text.append("\u2500" * 50 + "\n", style="dim")
    header_text.append("\n")

    return header_text, error_tb_syntax
