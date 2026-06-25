"""Rendering helpers and header building for agent display."""

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from rich.syntax import Syntax
from rich.text import Text

from sase.agent.agent_artifacts_cache import get_global_cache
from sase.ace.changespec.models import DeltaEntry
from sase.ace.tui.widgets.file_panel._diff import DIFF_CACHE_TTL_SECONDS
from sase.ace.tui.widgets.file_panel._linked_deltas import LinkedDeltaGroup
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_LEGEND_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
    plan_chain_feedback_round,
)

from ...models.agent import Agent, AttemptRecord
from ...models.agent_bead import (
    BEAD_DISPLAY_CACHE_MISS,
    cached_bead_display,
)
from .._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE
from ...util.lazy_syntax import lazy_renderable
from ._agent_artifacts import AgentArtifactPath
from ._helpers import (
    WORKFLOW_VARIABLES_SECTION_LABEL,
    append_model_field,
    extract_meta_fields,
    load_xprompts_used,
    should_render_agent_detail_model,
)
from ._file_path_hints import append_text_with_file_hints


@dataclass
class HeaderHintState:
    """Mutable file-hint state shared with hint-mode header rendering."""

    hint_counter: int
    hint_mappings: dict[int, str]
    workspace_dir: str | None


@dataclass(frozen=True)
class _DetailHeaderSummary:
    """Precomputed data that is too expensive for hot header rendering."""

    xprompts_used: list[dict[str, Any]] | None = None
    bead_display: str | None = None
    delta_entries: list[DeltaEntry] | None = None
    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = ()
    artifact_paths: list[AgentArtifactPath] | None = None
    memory_reads: tuple[MemoryReadDisplayEvent, ...] = ()
    skill_uses: tuple[SkillUseDisplayEvent, ...] = ()
    opened_workspaces: tuple[OpenedWorkspaceDisplayEvent, ...] = ()


@dataclass(frozen=True)
class _DetailHeaderSummaryCacheEntry:
    """Panel-local cached detail-header enrichment."""

    summary: _DetailHeaderSummary
    cached_monotonic: float


_PHASE_LABELS = {
    PLAN_CHAIN_PLAN_SUFFIX: "PLANNER",
    PLAN_CHAIN_CODER_SUFFIX: "CODER",
    PLAN_CHAIN_QUESTION_SUFFIX: "QUESTIONS",
    PLAN_CHAIN_EPIC_SUFFIX: "EPIC",
    PLAN_CHAIN_LEGEND_SUFFIX: "LEGEND",
    PLAN_CHAIN_COMMIT_SUFFIX: "COMMIT",
}

_UNASSIGNED_AGENT_NAME_DISPLAY = "unassigned"
_DETAIL_HEADER_SUMMARY_CACHE_MAX_ENTRIES = 256


def _detail_header_summary_cache(
    widget: object,
) -> OrderedDict[tuple[Any, ...], _DetailHeaderSummaryCacheEntry]:
    cache = getattr(widget, "_agent_detail_header_summary_cache", None)
    if cache is None:
        cache = OrderedDict()
        cast(Any, widget)._agent_detail_header_summary_cache = cache
    return cast(
        OrderedDict[tuple[Any, ...], _DetailHeaderSummaryCacheEntry],
        cache,
    )


def get_cached_detail_header_summary(
    widget: object,
    agent: Agent,
) -> _DetailHeaderSummary | None:
    """Return a cached detail-header summary for ``agent`` when available."""
    cache = _detail_header_summary_cache(widget)
    entry = cache.get(agent.identity)
    if entry is None:
        return None
    cache.move_to_end(agent.identity)
    return entry.summary


def should_refresh_detail_header_summary(
    widget: object,
    agent: Agent,
) -> bool:
    """Return whether ``agent``'s cached detail-header summary is absent/stale."""
    cache = _detail_header_summary_cache(widget)
    entry = cache.get(agent.identity)
    if entry is None:
        return True
    cache.move_to_end(agent.identity)
    return (time.monotonic() - entry.cached_monotonic) >= DIFF_CACHE_TTL_SECONDS


def cache_detail_header_summary(
    widget: object,
    agent: Agent,
    summary: _DetailHeaderSummary,
) -> None:
    """Store ``summary`` in ``widget``'s bounded detail-header cache."""
    cache = _detail_header_summary_cache(widget)
    cache[agent.identity] = _DetailHeaderSummaryCacheEntry(
        summary=summary,
        cached_monotonic=time.monotonic(),
    )
    cache.move_to_end(agent.identity)
    while len(cache) > _DETAIL_HEADER_SUMMARY_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)


def clear_detail_header_summary_cache(widget: object) -> None:
    """Clear ``widget``'s detail-header enrichment cache if it exists."""
    cache = getattr(widget, "_agent_detail_header_summary_cache", None)
    if cache is not None:
        cache.clear()


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


def build_detail_header_summary(agent: Agent) -> _DetailHeaderSummary:
    """Build expensive header enrichments outside hot selection rendering."""
    xprompts_used = None
    if agent.step_type not in ("bash", "python", "parallel"):
        xprompts_used = load_xprompts_used(agent)

    # Only confirmed bead displays surface in the header. A cache miss means
    # the candidate has not been confirmed against a bead store yet, so render
    # nothing here; the async worker resolves it off the event loop and the
    # header re-renders once a concrete issue is confirmed.
    bead_display = None
    if agent.agent_name:
        cached_display = cached_bead_display(agent)
        if cached_display is not BEAD_DISPLAY_CACHE_MISS:
            bead_display = cast(str | None, cached_display)

    from sase.ace.tui.memory_reads import load_memory_reads_for_agent_context
    from sase.ace.tui.opened_workspaces import (
        load_opened_workspaces_for_agent_context,
    )
    from sase.ace.tui.skill_uses import load_skill_uses_for_agent_context

    from ._agent_artifacts import agent_artifact_paths
    from ._agent_deltas import agent_delta_entries
    from ..file_panel._linked_deltas import get_cached_linked_delta_groups

    return _DetailHeaderSummary(
        xprompts_used=xprompts_used,
        bead_display=bead_display,
        delta_entries=agent_delta_entries(agent),
        linked_delta_groups=get_cached_linked_delta_groups(agent),
        artifact_paths=agent_artifact_paths(agent),
        memory_reads=load_memory_reads_for_agent_context(agent),
        skill_uses=load_skill_uses_for_agent_context(agent),
        opened_workspaces=load_opened_workspaces_for_agent_context(agent),
    )


def publish_opened_workspaces_cache(
    widget: object,
    agent: Agent,
    events: tuple[OpenedWorkspaceDisplayEvent, ...],
) -> None:
    """Hand off ``agent``'s opened-workspace events to the app (no I/O).

    The ``t`` keymap reads this in-memory cache to decide whether to open the
    tmux workspace chooser, so it never re-reads marker files on keypress.
    Resolving ``widget.app`` defensively keeps headless render stubs (which
    have no mounted app) working.
    """
    try:
        app = widget.app  # type: ignore[attr-defined]
    except (AttributeError, LookupError):
        return
    publisher = getattr(app, "publish_selected_agent_opened_workspaces", None)
    if callable(publisher):
        publisher(agent, events)


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
    suffix = canonical_plan_chain_suffix(agent.role_suffix)
    role = agent_family_role_for_suffix(
        agent.role_suffix,
        agent_family_role=agent.agent_family_role,
    )
    if role == "q":
        return "QUESTIONS"
    if role == "code":
        return "CODER"
    if role == "epic":
        return "EPIC"
    if role == "legend":
        return "LEGEND"
    if role == "commit":
        return "COMMIT"
    if role == "plan":
        return "PLANNER"
    if suffix in _PHASE_LABELS:
        return _PHASE_LABELS[suffix]
    feedback_round = plan_chain_feedback_round(
        suffix,
        agent_family_role=agent.agent_family_role,
    )
    if feedback_round is not None:
        return f"PLANNER (round {feedback_round})"
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


def render_agent_reply_content(
    agent: Agent,
    render_markdown: Callable[[str], object] | None = None,
) -> list:
    """Render one agent's reply (chunks, live reply, or response)."""
    render_markdown = render_markdown or (
        lambda content: lazy_renderable(content, "markdown")
    )
    renderables: list = []
    chunks = agent.get_timestamped_reply_chunks()
    if chunks:
        for ts, chunk_text in chunks:
            renderables.append(render_timestamp_divider(ts))
            content = chunk_text.strip()
            if content:
                renderables.append(render_markdown(content))
        return renderables
    live_reply = agent.get_live_reply_content()
    if live_reply:
        renderables.append(render_markdown(live_reply))
        return renderables
    response_content = agent.get_response_content()
    if response_content:
        renderables.append(render_markdown(response_content))
        return renderables
    chat_response = agent.get_chat_response_content()
    if chat_response:
        renderables.append(render_markdown(chat_response))
        return renderables
    return renderables


def build_header_text(
    agent: Agent,
    *,
    cheap: bool = False,
    hint_state: HeaderHintState | None = None,
    summary: _DetailHeaderSummary | None = None,
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
