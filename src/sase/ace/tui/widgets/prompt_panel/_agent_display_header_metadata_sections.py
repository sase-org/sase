"""Wait, turn, retry, tool-run, timestamp, and legacy member sections."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from typing import TYPE_CHECKING

from rich.text import Text

from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    QUEUED_STATUS,
    QUEUED_STATUS_COLOR,
    agent_status_bucket,
)
from ...models.agent import Agent
from .._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
)
from ._agent_display_header_metadata_identity import UNASSIGNED_AGENT_NAME_DISPLAY
from ._agent_display_state import DetailHeaderSummary, HeaderHintState
from ...models.agent_time import queued_for_label
from ._agent_turn_section import (
    TURN_LANE_LIMIT,
    TURN_SECTION_ID,
    ResponsiveTurnSection,
    build_agent_session_turn_lanes,
)
from ._agent_wait_section import (
    WAIT_SECTION_ID,
    ResponsiveWaitSection,
    build_wait_lanes,
)
from ._file_path_hints import append_text_with_file_hints
from ._helpers import (
    append_major_section_divider,
    append_model_field,
    append_section_heading,
    should_render_agent_detail_model,
)

if TYPE_CHECKING:
    from sase.core.wait_dependency_resolution import TribeWaitBinding


LEGACY_MEMBER_STATUS_STYLES: dict[str, str] = {
    "Stopped": "bold #FFAF5F",
    "Starting": "bold #87D7FF",
    "Running": "bold #FFD700",
    "Queued": f"bold {QUEUED_STATUS_COLOR}",
    "Waiting": "bold #AF87FF",
    "Failed": "bold #FF5F5F",
    "Done": "bold #5FD75F",
}


def append_wait_field(
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
        runners_only = True

    from ...models.agent_epic_follow_progress import (
        cached_epic_follow_progress_snapshot,
    )

    lanes = build_wait_lanes(
        agent,
        agent_status_buckets=agent_status_buckets,
        clan_wait_member_statuses=clan_wait_member_statuses,
        tribe_wait_bindings=tribe_wait_bindings,
        wait_bead_statuses=wait_bead_statuses,
        epic_follow_progress=cached_epic_follow_progress_snapshot(agent),
    )
    if runners_only:
        lanes = tuple(lane for lane in lanes if lane[0] == "capacity")
    if not lanes:
        return None

    section = ResponsiveWaitSection(lanes)
    start = len(text)
    text.append_text(section.logical_text)
    if responsive_ranges is not None:
        responsive_ranges[WAIT_SECTION_ID] = (start, len(text))
    return section


def append_turn_or_model_fields(
    text: Text,
    agent: Agent,
    responsive_ranges: MutableMapping[str, tuple[int, int]] | None,
) -> ResponsiveTurnSection | None:
    """Append agent_session ``Turns:`` lanes or a concrete-turn ``Model:`` field."""
    if agent.is_agent_session_container_row:
        lanes = build_agent_session_turn_lanes(agent)
        section = ResponsiveTurnSection(
            lanes=lanes[:TURN_LANE_LIMIT],
            hidden_count=max(0, len(lanes) - TURN_LANE_LIMIT),
        )
        start = len(text)
        text.append_text(section.logical_text)
        if responsive_ranges is not None:
            responsive_ranges[TURN_SECTION_ID] = (start, len(text))
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


def append_retry_fields(text: Text, agent: Agent) -> None:
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


def append_auto_restart_fields(text: Text, agent: Agent) -> None:
    """Append the auto-restart provenance block for replacement rows."""
    provenance = agent.auto_restart_provenance
    if not provenance:
        return
    from sase.agent.auto_restart.ux import auto_restart_provenance_lines

    for line in auto_restart_provenance_lines(provenance):
        text.append(f"{line}\n", style="#FFAF5F")
    evidence_dir = provenance.get("evidence_dir")
    if isinstance(evidence_dir, str) and evidence_dir:
        text.append("  evidence: ", style="dim #FFAF5F")
        text.append(f"{evidence_dir.rstrip('/')}/error_report.md", style="#FFAF5F")
        text.append(" (v)\n", style="dim #FFAF5F")


def append_tool_runs_field(
    text: Text,
    agent: Agent,
    summary: DetailHeaderSummary | None,
) -> None:
    """Append the expanded ``Tool runs:`` field, one entry per label (plan §3.7).

    Pure render of the ``tool-runs`` lane plus the in-memory glance
    overlay; live runs win per label. Remote and clan rows never show it.
    """

    from ...tool_runs.header_chip import tool_runs_field_entries
    from ...tool_runs.snapshot import get_snapshot

    node_summary = summary.tool_run_summary if summary is not None else None
    snapshot = get_snapshot()
    runs = snapshot.runs if snapshot is not None else ()
    silent_after_s = snapshot.silent_after_s if snapshot is not None else 60
    entries = tool_runs_field_entries(
        agent,
        node_summary,
        snapshot_runs=runs,
        snapshot_silent_after_s=silent_after_s,
    )
    if not entries:
        return
    text.append("Tool runs: ", style="bold #87D7FF")
    for index, entry in enumerate(entries):
        if index:
            text.append(" · ", style="dim")
        text.append(entry.text, style=entry.style)
    text.append("\n")


def append_timestamp_fields(
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


def append_legacy_parallel_members_section(text: Text, agent: Agent) -> None:
    """Preserve archived parallel-agent_session member summaries."""
    if not agent.agent_session_parallel:
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
        role = member.agent_session_role or "member"
        name = member.presented_agent_name or UNASSIGNED_AGENT_NAME_DISPLAY
        bucket = agent_status_bucket(member)
        glyph = AGENT_STATUS_BUCKET_GLYPHS[bucket]
        status_style = LEGACY_MEMBER_STATUS_STYLES[bucket]
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
