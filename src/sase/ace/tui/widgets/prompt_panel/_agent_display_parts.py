"""Rendering helpers and header building for agent display."""

from datetime import datetime

from rich.syntax import Syntax
from rich.text import Text

from sase.agent.agent_artifacts_cache import get_global_cache

from ...models.agent import Agent, AttemptRecord
from ...models.agent_bead import format_agent_bead_display
from ...util.lazy_syntax import lazy_renderable
from ._helpers import (
    append_model_field,
    extract_meta_fields,
    format_embedded_workflows,
    load_embedded_workflows,
)


def render_timestamp_divider(iso_timestamp: str) -> Text:
    """Create a styled timestamp divider: ``--- HH:MM:SS ---...---``."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        local_dt = dt.astimezone()
        time_str = local_dt.strftime("%H:%M:%S")
    except (ValueError, OSError):
        time_str = "??:??:??"
    prefix = f"\u2500\u2500\u2500 {time_str} "
    suffix_len = 50 - len(prefix)
    divider = Text()
    divider.append(prefix + "\u2500" * suffix_len + "\n", style="dim #D7D7FF")
    return divider


def get_phase_label(agent: Agent) -> str:
    """Map role_suffix to human-readable phase label."""
    suffix = agent.role_suffix
    if suffix == ".plan":
        return "PLANNER"
    if suffix == ".code":
        return "CODER"
    if suffix == ".q":
        return "QUESTIONS"
    if suffix == ".epic":
        return "EPIC"
    if suffix and suffix.startswith(".") and suffix[1:].isdigit():
        return f"PLANNER (round {suffix[1:]})"
    return "AGENT"


def render_attempt_divider(
    attempt: AttemptRecord | None,
    *,
    is_current: bool,
    fallback_model: str | None = None,
) -> Text:
    """Create a styled attempt divider.

    ``attempt=None`` with ``is_current=True`` produces the CURRENT/FINAL
    divider for the root live_reply. A record with ``status="raised"`` is
    the terminal failure — rendered with the current-attempt color since
    its content lives at the root.
    """
    divider = Text()
    if attempt is None:
        label = "ATTEMPT (current)"
        time_str = "??:??:??"
        color = "#AF87FF"
    else:
        label = f"ATTEMPT {attempt.attempt_number}"
        if attempt.used_fallback and attempt.model:
            label += f" via fallback → {attempt.model}"
        elif is_current and fallback_model:
            label += f" via fallback → {fallback_model}"
        try:
            time_str = attempt.start_hhmmss
        except (ValueError, OSError):
            time_str = "??:??:??"
        if is_current:
            color = "#AF87FF"
        else:
            color = "#FF8700"

    divider.append("─── ", style=f"dim {color}")
    divider.append(label, style=f"bold {color}")
    divider.append(f" ─── {time_str} ", style=f"dim {color}")
    used = 4 + len(label) + 5 + len(time_str) + 1
    remaining = max(50 - used, 3)
    divider.append("─" * remaining + "\n", style=f"dim {color}")
    if attempt is not None and attempt.status == "failed" and attempt.error_snippet:
        divider.append(f"  ✗ {attempt.error_snippet}\n", style="dim italic #FF5F5F")
    elif attempt is not None and attempt.status == "raised" and attempt.error_snippet:
        divider.append(f"  ✗ {attempt.error_snippet}\n", style="dim italic #FF5F5F")
    return divider


def render_phase_divider(label: str, start_time: datetime | None) -> Text:
    """Create a styled phase divider: ``--- LABEL --- HH:MM:SS ---...---``."""
    if start_time:
        try:
            local_dt = start_time.astimezone()
            time_str = local_dt.strftime("%H:%M:%S")
        except (ValueError, OSError):
            time_str = "??:??:??"
    else:
        time_str = "??:??:??"
    divider = Text()
    divider.append("\u2500\u2500\u2500 ", style="dim #AF87FF")
    divider.append(label, style="bold #AF87FF")
    divider.append(f" \u2500\u2500\u2500 {time_str} ", style="dim #AF87FF")
    used = 4 + len(label) + 5 + len(time_str) + 1
    remaining = max(50 - used, 3)
    divider.append("\u2500" * remaining + "\n", style="dim #AF87FF")
    return divider


def render_agent_reply_content(agent: Agent) -> list:
    """Render one agent's reply (chunks, live reply, or response)."""
    renderables: list = []
    chunks = agent.get_timestamped_reply_chunks()
    if chunks:
        for ts, chunk_text in chunks:
            renderables.append(render_timestamp_divider(ts))
            content = chunk_text.strip()
            if content:
                renderables.append(lazy_renderable(content, "markdown"))
        return renderables
    live_reply = agent.get_live_reply_content()
    if live_reply:
        renderables.append(lazy_renderable(live_reply, "markdown"))
        return renderables
    response_content = agent.get_response_content()
    if response_content:
        renderables.append(lazy_renderable(response_content, "markdown"))
        return renderables
    chat_response = agent.get_chat_response_content()
    if chat_response:
        renderables.append(lazy_renderable(chat_response, "markdown"))
        return renderables
    # Running Gemini thinking models buffer output until the session ends;
    # show a placeholder so the reply section isn't blank.
    if agent.status == "RUNNING" and agent.llm_provider == "gemini":
        placeholder = Text()
        placeholder.append(
            "Gemini is thinking\u2026 Reply will appear when response "
            "generation begins.\n",
            style="dim italic",
        )
        renderables.append(placeholder)
    return renderables


def build_header_text(
    agent: Agent, *, cheap: bool = False
) -> tuple[Text, Syntax | None]:
    """Build the AGENT DETAILS header section with trailing separator.

    Contains agent metadata (name, workspace, model, timestamps, etc.),
    error information, and a trailing separator line.

    Args:
        agent: The agent to render a header for.
        cheap: When True, skip any disk-touching enrichments (e.g. embedded
            workflow metadata loaded from disk). Used by the j/k immediate
            path so the header renders within one frame; the debounced full
            update fills in the omitted fields.

    Returns:
        Tuple of (header_text, error_traceback_syntax).
    """
    header_text = Text()

    # Header - AGENT DETAILS
    header_text.append("AGENT DETAILS\n", style="bold #D7AF5F underline")
    header_text.append("\n")

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
    meta_project = None
    meta_changespec = None
    if agent.step_output and isinstance(agent.step_output, dict):
        meta_project = agent.step_output.get("meta_project")
        meta_changespec = agent.step_output.get("meta_changespec")

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

    # Embedded Workflows (if available) - only for agent/prompt steps.
    # Skipped on the cheap path: load_embedded_workflows touches disk, and
    # the debounced full update will populate this field shortly after.
    if not cheap and agent.step_type not in ("bash", "python", "parallel"):
        embedded_workflows = load_embedded_workflows(agent)
        if embedded_workflows:
            header_text.append("Embedded Workflows: ", style="bold #87D7FF")
            header_text.append(f"{format_embedded_workflows(embedded_workflows)}\n")

    # Model (with provider-themed styling)
    append_model_field(header_text, agent.model, agent.llm_provider)

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

    # Agent name (when assigned via %name directive or manual TUI naming)
    if agent.agent_name:
        header_text.append("Name: ", style="bold #87D7FF")
        header_text.append(f"@{agent.agent_name}\n", style="#FF87D7")
        bead_display = format_agent_bead_display(agent, include_description=not cheap)
        if bead_display:
            header_text.append("Bead: ", style="bold #87D7FF")
            header_text.append(f"{bead_display}\n", style="bold #FFAF00")

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
    header_text.append("Timestamps: ", style="bold #87D7FF")
    header_text.append(f"{agent.timestamps_display}\n", style="#D7D7FF")

    # Meta fields from step output
    if agent.step_output and isinstance(agent.step_output, dict):
        meta_fields = extract_meta_fields(agent.step_output)
        if meta_fields:
            header_text.append("\n")
            for name, value in meta_fields:
                header_text.append(f"{name}: ", style="bold #87D7FF")
                header_text.append(f"{value}\n", style="#5FD75F")

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


def get_prompt_content(agent: Agent) -> str | None:
    """Get the prompt content for the agent.

    Returns:
        Prompt content, or None if not found.
    """
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir is None:
        return None

    cache = get_global_cache()
    selected = cache.select_prompt_file(
        artifacts_dir,
        is_workflow_child=agent.is_workflow_child,
        step_name=agent.step_name,
    )
    if selected is None:
        return None
    return cache.read_text(selected)
