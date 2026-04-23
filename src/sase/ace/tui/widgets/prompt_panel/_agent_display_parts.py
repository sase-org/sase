"""Rendering helpers and header building for agent display."""

from datetime import datetime
from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text

from ...models.agent import Agent, AttemptRecord
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


def render_agent_reply_content(agent: Agent) -> list[Text | Syntax]:
    """Render one agent's reply (chunks, live reply, or response)."""
    renderables: list[Text | Syntax] = []
    chunks = agent.get_timestamped_reply_chunks()
    if chunks:
        for ts, chunk_text in chunks:
            renderables.append(render_timestamp_divider(ts))
            content = chunk_text.strip()
            if content:
                renderables.append(
                    Syntax(content, "markdown", theme="monokai", word_wrap=True)
                )
        return renderables
    live_reply = agent.get_live_reply_content()
    if live_reply:
        renderables.append(
            Syntax(live_reply, "markdown", theme="monokai", word_wrap=True)
        )
        return renderables
    response_content = agent.get_response_content()
    if response_content:
        renderables.append(
            Syntax(
                response_content,
                "markdown",
                theme="monokai",
                word_wrap=True,
            )
        )
        return renderables
    chat_response = agent.get_chat_response_content()
    if chat_response:
        renderables.append(
            Syntax(
                chat_response,
                "markdown",
                theme="monokai",
                word_wrap=True,
            )
        )
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


def build_header_text(agent: Agent) -> tuple[Text, Syntax | None]:
    """Build the AGENT DETAILS header section with trailing separator.

    Contains agent metadata (name, workspace, model, timestamps, etc.),
    error information, and a trailing separator line.

    Returns:
        Tuple of (header_text, error_traceback_syntax).
    """
    header_text = Text()

    # Header - AGENT DETAILS
    header_text.append("AGENT DETAILS\n", style="bold #D7AF5F underline")
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

    # Embedded Workflows (if available) - only for agent/prompt steps
    if agent.step_type not in ("bash", "python", "parallel"):
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

    # Waiting info (when agent is waiting for dependencies, a duration, or absolute time)
    if agent.waiting_for or agent.wait_duration or agent.wait_until:
        from sase.ace.tui.models.agent import format_compact_duration, format_wait_until

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
            from datetime import datetime as _dt

            target = _dt.fromisoformat(agent.wait_until)
            remaining = (target - _dt.now()).total_seconds()
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

    artifacts_path = Path(artifacts_dir)

    # Look for any *_prompt.md file
    prompt_files = list(artifacts_path.glob("*_prompt.md"))

    if not prompt_files:
        return None

    # For workflow child agents, filter to the step-specific prompt file.
    # All workflow steps share the same artifacts_dir, so without filtering
    # we'd always show the most recently modified prompt (usually the last
    # step).
    if agent.is_workflow_child and agent.step_name:
        step_specific = [
            p for p in prompt_files if p.name.endswith(f"-{agent.step_name}_prompt.md")
        ]
        if step_specific:
            prompt_files = step_specific

    # Sort by modification time to get the most recent
    prompt_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    try:
        with open(prompt_files[0], encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None
