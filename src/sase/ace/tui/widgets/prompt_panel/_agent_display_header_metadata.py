"""Metadata field rendering for the agent detail header."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text

from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    QUEUED_STATUS,
    QUEUED_STATUS_COLOR,
    agent_status_bucket,
)
from sase.core.wait_dependency_resolution import TribeWaitBinding
from sase.plan_tier_presentation import PLAN_TIER_PRESENTATIONS
from sase.project_display_names import humanize_cl_name

from ...models.agent import Agent
from .._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _FAMILY_NAME_STYLE,
    _PROC_SHELL_ID_STYLE,
)
from ._agent_display_state import DetailHeaderSummary, HeaderHintState
from ...models.agent_time import queued_for_label
from ._agent_page_section import (
    AGENT_PAGE_SECTION_ID,
    ResponsiveAgentPageSection,
)
from ._file_path_hints import append_text_with_file_hints
from ._helpers import (
    append_major_section_divider,
    append_model_field,
    append_section_heading,
    extract_meta_fields,
    project_display_label,
    should_render_agent_detail_model,
)
from ._agent_shell_section import (
    SHELL_LANE_LIMIT,
    SHELL_SECTION_ID,
    ResponsiveShellSection,
    build_family_shell_lanes,
)
from ._agent_wait_section import (
    WAIT_SECTION_ID,
    ResponsiveWaitSection,
    build_wait_lanes,
)


_UNASSIGNED_AGENT_NAME_DISPLAY = "unassigned"
_AUTO_APPROVE_KIND_STYLES: dict[str, tuple[str, str]] = {
    "plan": ("\u26a1 PLAN", "bold #5FD7FF"),
    **{
        tier: (f"\u26a1 {tier.upper()}", presentation.rich_style)
        for tier, presentation in PLAN_TIER_PRESENTATIONS.items()
    },
}
_LEGACY_MEMBER_STATUS_STYLES: dict[str, str] = {
    "Stopped": "bold #FFAF5F",
    "Starting": "bold #87D7FF",
    "Running": "bold #FFD700",
    "Queued": f"bold {QUEUED_STATUS_COLOR}",
    "Waiting": "bold #AF87FF",
    "Failed": "bold #FF5F5F",
    "Done": "bold #5FD75F",
}


@dataclass(frozen=True, slots=True)
class _AgentMetadataFields:
    """Core metadata fields and responsive sections appended to a header."""

    meta_fields: list[tuple[str, str]]
    page_section: ResponsiveAgentPageSection | None
    wait_section: ResponsiveWaitSection | None
    shell_section: ResponsiveShellSection | None


def _append_auto_approve_field(text: Text, agent: Agent) -> None:
    """Append the ``Auto:`` auto-approve kind field for autonomous agents."""
    if not agent.approve:
        return
    kind = agent.auto_approve_plan_action or "plan"
    token, style = _AUTO_APPROVE_KIND_STYLES.get(
        kind, (f"\u26a1 {kind.upper()}", "bold #BCBCBC")
    )
    text.append("Auto: ", style="bold #87D7FF")
    text.append(f"{token}\n", style=style)


def _append_identity_fields(
    text: Text,
    agent: Agent,
    summary: DetailHeaderSummary | None,
    cached_bead_display: Callable[[Agent], object],
    responsive_ranges: MutableMapping[str, tuple[int, int]] | None,
) -> ResponsiveAgentPageSection | None:
    """Append agent identity and retry-chain fields."""
    text.append("Name: ", style="bold #87D7FF")
    presented_name = agent.presented_agent_name or agent.agent_name
    if presented_name:
        name_style = (
            _FAMILY_NAME_STYLE
            if agent.is_family_container_row
            else _PROC_SHELL_ID_STYLE
            if agent.is_proc_shell
            else _AGENT_NAME_ANNOTATION_STYLE
        )
        text.append(f"{presented_name}\n", style=name_style)
        # Structured bead identity belongs exclusively to the deferred BEAD lane.
        is_known_phase = bool(agent.phase_bead_id or agent.agent_family_role == "phase")
        if summary is not None and summary.bead_summary is not None:
            bead_display = None
        elif is_known_phase:
            bead_display = None
        elif summary is not None:
            bead_display = summary.bead_display
        else:
            cached_display = cached_bead_display(agent)
            bead_display = cached_display if isinstance(cached_display, str) else None
        if bead_display:
            text.append("Bead: ", style="bold #87D7FF")
            text.append(f"{bead_display}\n", style="bold #FFAF00")
    else:
        text.append(f"{_UNASSIGNED_AGENT_NAME_DISPLAY}\n", style="dim")

    page_section = None
    if summary is not None and summary.agent_page_url:
        page_section = ResponsiveAgentPageSection(summary.agent_page_url)
        start = len(text)
        text.append_text(page_section.logical_text)
        if responsive_ranges is not None:
            responsive_ranges[AGENT_PAGE_SECTION_ID] = (start, len(text))

    if agent.is_retry_attempt or agent.is_retried_parent:
        text.append("Retry chain: ", style="bold #87D7FF")
        text.append("↻ ", style="bold #FFAF00")
        if agent.is_retry_attempt:
            text.append(f"attempt #{agent.retry_attempt}", style="#FFAF00")
            if agent.retry_error_category:
                text.append(f" ({agent.retry_error_category})", style="dim #FFAF00")
        if agent.is_retried_parent:
            if agent.is_retry_attempt:
                text.append(", ", style="dim")
            text.append("handed off to retry", style="dim #FFAF00")
        text.append("\n")
    return page_section


def _append_project_fields(
    text: Text,
    agent: Agent,
    *,
    meta_project: object,
    meta_patch: object,
) -> None:
    """Append project, workspace, and workflow identity fields."""
    if agent.is_proc_shell:
        if agent.cl_name and agent.cl_name != "proc":
            text.append("Project: ", style="bold #87D7FF")
            label = agent.project_display_name or humanize_cl_name(agent.cl_name)
            text.append(f"{label}\n", style="#00D7AF")
        if agent.workspace_num is not None and agent.workspace_num > 0:
            text.append("Workspace: ", style="bold #87D7FF")
            text.append(f"#{agent.workspace_num}\n", style="#5FD7FF")
        if agent.monitor_cwd:
            text.append("Cwd: ", style="bold #87D7FF")
            text.append(f"{agent.monitor_cwd}\n", style="#D7D7FF")
        return

    if (
        agent.is_workflow_step_child
        and agent.step_type in {"bash", "python"}
        and agent.step_name
    ):
        text.append("Step: ", style="bold #87D7FF")
        text.append(f"{agent.step_name}\n", style="#00D7AF")
    elif meta_patch:
        text.append("Patch: ", style="bold #87D7FF")
        text.append(f"{meta_patch}", style="#00D7AF")
        if agent.cl_num:
            text.append(" (")
            text.append(agent.cl_num, style="bold underline #569CD6")
            text.append(")")
        text.append("\n")
    elif meta_project:
        text.append("Project: ", style="bold #87D7FF")
        text.append(f"{project_display_label(agent, meta_project)}\n", style="#00D7AF")
    elif agent.is_project_agent:
        text.append("Project: ", style="bold #87D7FF")
        text.append(f"{project_display_label(agent, agent.cl_name)}\n", style="#00D7AF")
    else:
        text.append("Patch: ", style="bold #87D7FF")
        text.append(humanize_cl_name(agent.cl_name), style="#00D7AF")
        if agent.cl_num:
            text.append(" (")
            text.append(agent.cl_num, style="bold underline #569CD6")
            text.append(")")
        text.append("\n")

    workspace_num = agent.effective_workspace_num
    if workspace_num is not None and workspace_num > 0:
        text.append("Workspace: ", style="bold #87D7FF")
        text.append(f"#{workspace_num}\n", style="#5FD7FF")

    if agent.workflow and not agent.appears_as_agent:
        text.append("Workflow: ", style="bold #87D7FF")
        text.append(f"{agent.workflow}\n")


def _append_wait_field(
    text: Text,
    agent: Agent,
    agent_status_buckets: Mapping[str, str] | None,
    clan_wait_member_statuses: Mapping[str, Sequence[tuple[str, str]]] | None,
    tribe_wait_bindings: Mapping[tuple[object, str], TribeWaitBinding] | None,
    runner_queue_ahead_count: int | None,
    wait_bead_statuses: Sequence[tuple[str, str | None]] | None,
    responsive_ranges: MutableMapping[str, tuple[int, int]] | None,
) -> ResponsiveWaitSection | None:
    """Append dependency, time-floor, and runner-slot wait details."""
    from sase.ace.tui.models.agent import wait_display_agent

    wait_agent = wait_display_agent(agent)
    runners_only = False
    if agent.status == QUEUED_STATUS:
        text.append("Queue: ", style="bold #87D7FF")
        position = wait_agent.runner_slot_queue_position
        queue_size = wait_agent.runner_slot_queue_size
        if position is not None:
            text.append(f"#{position}", style=f"bold {QUEUED_STATUS_COLOR}")
            if queue_size is not None:
                text.append(f" of {queue_size}", style=QUEUED_STATUS_COLOR)
        else:
            text.append("pending", style=f"bold {QUEUED_STATUS_COLOR}")
        if runner_queue_ahead_count is not None:
            text.append(" · ", style="dim")
            if runner_queue_ahead_count:
                text.append(
                    f"{runner_queue_ahead_count} ahead",
                    style=QUEUED_STATUS_COLOR,
                )
            else:
                text.append("at the front", style=QUEUED_STATUS_COLOR)
        queued_for = queued_for_label(wait_agent.slot_requested_at)
        if queued_for is not None:
            text.append(" · ", style="dim")
            text.append(f"{queued_for} in queue", style=QUEUED_STATUS_COLOR)
        text.append("\n")
        if not (wait_agent.wait_runners_explicit or wait_agent.wait_priority_explicit):
            return None
        runners_only = True

    lanes = build_wait_lanes(
        agent,
        agent_status_buckets=agent_status_buckets,
        clan_wait_member_statuses=clan_wait_member_statuses,
        tribe_wait_bindings=tribe_wait_bindings,
        wait_bead_statuses=wait_bead_statuses,
    )
    if runners_only:
        lanes = tuple(lane for lane in lanes if lane[0] == "runners")
    if not lanes:
        return None

    section = ResponsiveWaitSection(lanes)
    start = len(text)
    text.append_text(section.logical_text)
    if responsive_ranges is not None:
        responsive_ranges[WAIT_SECTION_ID] = (start, len(text))
    return section


def _append_shell_or_model_fields(
    text: Text,
    agent: Agent,
    responsive_ranges: MutableMapping[str, tuple[int, int]] | None,
) -> ResponsiveShellSection | None:
    """Append family ``Shells:`` lanes or a concrete-shell ``Model:`` field."""
    if agent.is_family_container_row:
        lanes = build_family_shell_lanes(agent)
        section = ResponsiveShellSection(
            lanes=lanes[:SHELL_LANE_LIMIT],
            hidden_count=max(0, len(lanes) - SHELL_LANE_LIMIT),
        )
        start = len(text)
        text.append_text(section.logical_text)
        if responsive_ranges is not None:
            responsive_ranges[SHELL_SECTION_ID] = (start, len(text))
        return section
    if should_render_agent_detail_model(agent):
        append_model_field(
            text,
            agent.model,
            agent.llm_provider,
            agent.reasoning_effort,
            agent.model_alias,
        )
    return None


def _append_retry_fields(text: Text, agent: Agent) -> None:
    """Append retry history and fallback model fields."""
    if not (agent.retry_count > 0 or agent.using_fallback or agent.attempt_history):
        return
    text.append("Retries: ", style="bold #87D7FF")
    text.append(f"{agent.retry_count}/{agent.max_retries}\n", style="#FF8700")
    for record in agent.attempt_history:
        try:
            hhmmss = record.start_hhmmss
        except (ValueError, OSError):
            hhmmss = "??:??:??"
        snippet = record.error_snippet or record.status
        fb_marker = " (fallback)" if record.used_fallback else ""
        text.append(
            f"  Attempt {record.attempt_number} · {hhmmss}{fb_marker} · "
            f"{record.status}: {snippet}\n",
            style="dim #FF8700",
        )
    if agent.fallback_model:
        text.append("Fallback: ", style="bold #87D7FF")
        style = "bold #FF8700" if agent.using_fallback else "dim #FF8700"
        text.append(f"{agent.fallback_model}\n", style=style)


def _append_timestamp_fields(
    text: Text,
    agent: Agent,
    hint_state: HeaderHintState | None,
) -> None:
    """Append activity and timestamp fields, including selectable file hints."""
    if agent.activity:
        text.append("Activity: ", style="bold #87D7FF")
        text.append(f"{agent.activity}\n", style="bold #D7AF5F")

    text.append("Timestamps: ", style="bold #87D7FF")
    if hint_state is None:
        text.append(f"{agent.timestamps_display}\n", style="#D7D7FF")
    else:
        hint_state.hint_counter = append_text_with_file_hints(
            text,
            f"{agent.timestamps_display}\n",
            hint_state.hint_counter,
            hint_state.hint_mappings,
            hint_state.workspace_dir,
            style="#D7D7FF",
        )


def append_agent_metadata_fields(
    text: Text,
    agent: Agent,
    *,
    cheap: bool,
    hint_state: HeaderHintState | None,
    summary: DetailHeaderSummary | None,
    agent_status_buckets: Mapping[str, str] | None,
    cached_bead_display: Callable[[Agent], object],
    clan_wait_member_statuses: Mapping[str, Sequence[tuple[str, str]]] | None = None,
    tribe_wait_bindings: Mapping[tuple[object, str], TribeWaitBinding] | None = None,
    runner_queue_ahead_count: int | None = None,
    responsive_ranges: MutableMapping[str, tuple[int, int]] | None = None,
) -> _AgentMetadataFields:
    """Append core metadata and return workflow fields plus responsive lanes."""
    page_section = _append_identity_fields(
        text,
        agent,
        summary,
        cached_bead_display,
        responsive_ranges,
    )

    step_output = agent.step_output if isinstance(agent.step_output, dict) else None
    meta_project = step_output.get("meta_project") if step_output is not None else None
    meta_patch = (
        step_output.get("meta_patch")
        or step_output.get("meta_changespec")  # legacy compatibility alias
        if step_output is not None
        else None
    )
    meta_fields = extract_meta_fields(step_output) if step_output is not None else []
    _append_project_fields(
        text,
        agent,
        meta_project=meta_project,
        meta_patch=meta_patch,
    )

    _append_auto_approve_field(text, agent)
    shell_section = _append_shell_or_model_fields(text, agent, responsive_ranges)

    if not agent.is_proc_shell and not cheap and summary is not None:
        from ._agent_xprompts import append_agent_xprompts_section

        project_key = (
            Path(agent.project_file).parent.name if agent.project_file else None
        )
        append_agent_xprompts_section(
            text,
            summary.xprompts_used,
            project_key=project_key,
            project_display_name=agent.project_display_name,
        )

    if agent.vcs_provider:
        text.append("VCS: ", style="bold #87D7FF")
        text.append(f"{agent.vcs_provider}\n", style="#5FD7AF")
    if agent.pid:
        text.append("PID: ", style="bold #87D7FF")
        text.append(f"{agent.pid}\n", style="#FF87D7 bold")
    if agent.bug:
        text.append("BUG: ", style="bold #87D7FF")
        text.append(f"{agent.bug}\n", style="bold underline #569CD6")

    if agent.is_proc_shell:
        wait_section = None
    else:
        wait_section = _append_wait_field(
            text,
            agent,
            agent_status_buckets,
            clan_wait_member_statuses,
            tribe_wait_bindings,
            runner_queue_ahead_count,
            summary.wait_bead_statuses if summary is not None else None,
            responsive_ranges,
        )
        _append_retry_fields(text, agent)
    _append_timestamp_fields(text, agent, hint_state)
    return _AgentMetadataFields(meta_fields, page_section, wait_section, shell_section)


def append_legacy_parallel_members_section(text: Text, agent: Agent) -> None:
    """Preserve archived parallel-family member summaries."""
    if not agent.agent_family_parallel:
        return

    from ...models._agent_clan import clan_members

    members = sorted(
        clan_members(agent),
        key=lambda member: (
            member.start_time is None,
            member.start_time.isoformat() if member.start_time is not None else "",
            member.agent_name or "",
        ),
    )
    if not members:
        return

    append_major_section_divider(text)
    heading = Text("MEMBERS", style="bold #D7AF5F underline")
    heading.append(f" · {len(members)}", style="dim")
    append_section_heading(text, heading, section_id="members")

    for member in members:
        role = member.agent_family_role or "member"
        name = member.presented_agent_name or _UNASSIGNED_AGENT_NAME_DISPLAY
        bucket = agent_status_bucket(member)
        glyph = AGENT_STATUS_BUCKET_GLYPHS[bucket]
        status_style = _LEGACY_MEMBER_STATUS_STYLES[bucket]
        model = member.model or "default"

        text.append(role, style="italic #AF87FF")
        text.append(" · ", style="dim")
        text.append(name, style=_AGENT_NAME_ANNOTATION_STYLE)
        text.append(" · ", style="dim")
        text.append(f"{glyph} {member.display_status}", style=status_style)
        text.append(" · ", style="dim")
        text.append(model, style="#5FD7FF")
        text.append(" · ", style="dim")
        text.append(f"{member.duration_display}\n", style="dim #D7D7FF")
