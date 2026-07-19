"""Metadata field rendering for the agent detail header."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from rich.text import Text

from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    status_bucket_for_values,
)
from sase.project_display_names import humanize_cl_name

from ...models.agent import Agent
from .._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _FAMILY_NAME_STYLE,
)
from ._agent_display_state import DetailHeaderSummary, HeaderHintState
from ._file_path_hints import append_text_with_file_hints
from ._helpers import (
    append_major_section_divider,
    append_model_field,
    append_section_heading,
    extract_meta_fields,
    project_display_label,
    should_render_agent_detail_model,
)


_UNASSIGNED_AGENT_NAME_DISPLAY = "unassigned"
_UNKNOWN_WAIT_AGENT_GLYPH = "?"
_UNKNOWN_WAIT_AGENT_GLYPH_STYLE = "bold #FFAF5F"
_WAITING_VALUE_STYLE = "#FF87D7"
# Glyphs mirror ``AGENT_STATUS_BUCKET_GLYPHS``; colors mirror agent-row status
# accents in ``_agent_list_render_agent.py`` / ``models.agent_status``.
_WAIT_STATUS_BADGES: dict[str, tuple[str, str]] = {
    "Running": (AGENT_STATUS_BUCKET_GLYPHS["Running"], "bold #FFD700"),
    "Waiting": (AGENT_STATUS_BUCKET_GLYPHS["Waiting"], "bold #AF87FF"),
    "Starting": (AGENT_STATUS_BUCKET_GLYPHS["Starting"], "bold #87D7FF"),
    "Done": (AGENT_STATUS_BUCKET_GLYPHS["Done"], "bold #5FD75F"),
    "Failed": (AGENT_STATUS_BUCKET_GLYPHS["Failed"], "bold #FF5F5F"),
    "Stopped": (AGENT_STATUS_BUCKET_GLYPHS["Stopped"], "bold #8787AF"),
}
_AUTO_APPROVE_KIND_STYLES: dict[str, tuple[str, str]] = {
    "plan": ("\u26a1 PLAN", "bold #5FD7FF"),
    "tale": ("\u26a1 TALE", "bold #FFD75F"),
    "epic": ("\u26a1 EPIC", "bold #AF87FF"),
}
_LEGACY_MEMBER_STATUS_STYLES: dict[str, str] = {
    "Stopped": "bold #FFAF5F",
    "Starting": "bold #87D7FF",
    "Running": "bold #FFD700",
    "Waiting": "bold #AF87FF",
    "Failed": "bold #FF5F5F",
    "Done": "bold #5FD75F",
}


def _append_wait_status_badge(text: Text, bucket: str | None) -> None:
    """Append the standard badge for a known or unknown wait target."""
    badge = _WAIT_STATUS_BADGES.get(bucket) if bucket is not None else None
    if badge is None:
        glyph, style = (
            _UNKNOWN_WAIT_AGENT_GLYPH,
            _UNKNOWN_WAIT_AGENT_GLYPH_STYLE,
        )
    else:
        glyph, style = badge
    text.append(" ")
    text.append(glyph, style=style)


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
) -> None:
    """Append agent identity and retry-chain fields."""
    text.append("Name: ", style="bold #87D7FF")
    presented_name = agent.presented_agent_name or agent.agent_name
    if presented_name:
        name_style = (
            _FAMILY_NAME_STYLE
            if agent.is_family_container_row
            else _AGENT_NAME_ANNOTATION_STYLE
        )
        text.append(f"{presented_name}\n", style=name_style)
        # Phase identity belongs exclusively to the deferred BEAD context lane.
        is_known_phase = bool(agent.phase_bead_id or agent.agent_family_role == "phase")
        if summary is not None and summary.phase_bead is not None:
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


def _append_project_fields(
    text: Text,
    agent: Agent,
    *,
    meta_project: object,
    meta_changespec: object,
) -> None:
    """Append project, workspace, and workflow identity fields."""
    if agent.is_workflow_step_child and agent.step_name:
        text.append("Step: ", style="bold #87D7FF")
        text.append(f"{agent.step_name}\n", style="#00D7AF")
    elif meta_changespec:
        text.append("ChangeSpec: ", style="bold #87D7FF")
        text.append(f"{meta_changespec}", style="#00D7AF")
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
        text.append("ChangeSpec: ", style="bold #87D7FF")
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
) -> None:
    """Append dependency, time-floor, and runner-slot wait details."""
    from sase.ace.tui.models.agent import (
        format_compact_duration,
        format_wait_until,
        wait_display_agent,
        wait_remaining_seconds,
    )

    wait_agent = wait_display_agent(agent)
    has_slot_wait = bool(
        wait_agent.slot_requested_at and wait_agent.wait_runners is not None
    )
    if not (
        wait_agent.waiting_for
        or wait_agent.wait_duration
        or wait_agent.wait_until
        or has_slot_wait
    ):
        return

    text.append("Wait: ", style="bold #87D7FF")
    appended_dependency_names = False
    if wait_agent.waiting_for:
        for index, name in enumerate(wait_agent.waiting_for):
            if index:
                text.append(", ", style=_WAITING_VALUE_STYLE)
            text.append(name, style=_WAITING_VALUE_STYLE)
            clan_members = (
                clan_wait_member_statuses.get(name)
                if clan_wait_member_statuses is not None
                else None
            )
            if clan_members is not None:
                done_count = sum(bucket == "Done" for _label, bucket in clan_members)
                text.append(" (", style="dim #AF87FF")
                text.append("all clan members", style="bold #AF87FF")
                text.append(
                    f" · {done_count}/{len(clan_members)} done: ",
                    style="dim #AF87FF",
                )
                for member_index, (label, bucket) in enumerate(clan_members):
                    if member_index:
                        text.append(" · ", style="dim #AF87FF")
                    text.append(label, style=_WAITING_VALUE_STYLE)
                    _append_wait_status_badge(text, bucket)
                text.append(")", style="dim #AF87FF")
            elif agent_status_buckets is not None:
                _append_wait_status_badge(text, agent_status_buckets.get(name))
        appended_dependency_names = True

    time_part: str | None = None
    if wait_agent.wait_until:
        time_part = f"until {format_wait_until(wait_agent.wait_until)}"
    elif wait_agent.wait_duration:
        time_part = format_compact_duration(wait_agent.wait_duration)
    if time_part:
        if appended_dependency_names:
            text.append(" + ", style=_WAITING_VALUE_STYLE)
        text.append(time_part, style=_WAITING_VALUE_STYLE)
        appended_dependency_names = True

    remaining = wait_remaining_seconds(agent)
    if remaining is not None and remaining > 0:
        text.append(
            f" ({format_compact_duration(remaining)} left)",
            style="dim #AF87FF",
        )
    if has_slot_wait:
        if appended_dependency_names:
            text.append(" + ", style=_WAITING_VALUE_STYLE)
        in_use = wait_agent.runner_slots_in_use
        threshold = wait_agent.wait_runners
        assert threshold is not None
        if wait_agent.wait_runners_explicit:
            text.append(f"runners ≤ {threshold}", style=_WAITING_VALUE_STYLE)
            if threshold == 0:
                text.append(" (drain barrier)", style="bold #AF87FF")
            if in_use is not None:
                noun = "runner" if in_use == 1 else "runners"
                text.append(
                    f" · {in_use} {noun} still running",
                    style="dim #AF87FF",
                )
        elif in_use is not None:
            text.append(
                f"runners: {in_use}/{threshold + 1} in use",
                style=_WAITING_VALUE_STYLE,
            )
        else:
            text.append(
                f"runners: cap {threshold + 1}",
                style=_WAITING_VALUE_STYLE,
            )
        position = wait_agent.runner_slot_queue_position
        queue_size = wait_agent.runner_slot_queue_size
        if position is not None and queue_size is not None:
            text.append(
                f" · eligible #{position} of {queue_size}",
                style="dim #AF87FF",
            )
        elif in_use is not None and in_use > threshold:
            text.append(" · not currently eligible", style="dim #AF87FF")
    text.append("\n")


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
) -> list[tuple[str, str]]:
    """Append the core agent metadata rows and return workflow meta fields."""
    _append_identity_fields(text, agent, summary, cached_bead_display)

    step_output = agent.step_output if isinstance(agent.step_output, dict) else None
    meta_project = step_output.get("meta_project") if step_output is not None else None
    meta_changespec = (
        step_output.get("meta_changespec") if step_output is not None else None
    )
    meta_fields = extract_meta_fields(step_output) if step_output is not None else []
    _append_project_fields(
        text,
        agent,
        meta_project=meta_project,
        meta_changespec=meta_changespec,
    )

    _append_auto_approve_field(text, agent)
    if should_render_agent_detail_model(agent):
        append_model_field(
            text, agent.model, agent.llm_provider, agent.reasoning_effort
        )

    if not cheap and summary is not None:
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

    _append_wait_field(
        text,
        agent,
        agent_status_buckets,
        clan_wait_member_statuses,
    )
    _append_retry_fields(text, agent)
    _append_timestamp_fields(text, agent, hint_state)
    return meta_fields


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
        name = member.agent_name or _UNASSIGNED_AGENT_NAME_DISPLAY
        bucket = status_bucket_for_values(member.status)
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
