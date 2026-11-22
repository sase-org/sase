"""Header rendering for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime as DateTime
from typing import TYPE_CHECKING

from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.llm_calls._constants import SLOW_TOOL_CALL_THRESHOLD_MS

from ...models.agent import Agent, AgentType
from ...models.agent_bead import cached_bead_display
from ...models.agent_session_members import agent_session_roster_container
from ...models.agent_session_members import concrete_agent_session_turn_rows
from ...models.agent_hoods import agent_owns_sase_agent
from ...models.fold_scale import (
    AGENT_SESSION_FOLD_SCALE,
    effective_fold_level,
    lane_fold_scale,
)
from ...models.fold_state import FoldLevel
from .._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE, _NAMED_PROC_ROW_STYLE
from ._agent_display_agent_session import (
    SESSION_IDENTITY_COLOR,
    append_agent_session_fold_heading,
    append_agent_session_member_roster,
    effective_agent_session_fold_level,
    agent_session_roster_entries,
    agent_session_roster_heading_suffix,
)
from ._agent_display_neighbors import append_lane_neighbors_section
from ._agent_display_header_metadata import (
    append_agent_metadata_fields,
    append_legacy_parallel_members_section,
)
from ._agent_display_header_context import append_header_context_sections
from ._agent_display_header_finish import finish_header_text
from ._agent_display_header_renderable import (
    AgentHeader,
    AgentHeaderRenderable as AgentHeaderRenderable,
)
from ._agent_display_state import DetailHeaderSummary, HeaderHintState
from ._agent_output_variables import append_agent_output_variables_section
from ._fold_language import append_fold_header_line
from ._helpers import (
    WORKFLOW_VARIABLES_SECTION_LABEL,
    append_kind_header,
    append_major_section_divider,
    append_section_heading,
)
from ._identity_header import identity_kind_for_agent
from ._identity_header_compact import build_hijack_header_callout

if TYPE_CHECKING:
    from sase.core.agent_models import AgentModelSummary, AgentModelTurnFact
    from sase.core.wait_dependency_resolution import TribeWaitBinding

    from ...models._agent_clan_sections import ClanSectionSnapshot
    from ...models.sase_agent_neighbors import SaseAgentNeighborProjection
    from ...models.agent_runner_slots import RunnerCapacitySnapshot
    from ._member_roster import MemberJumpMap


def build_header_text(
    agent: Agent,
    *,
    cheap: bool = False,
    hint_state: HeaderHintState | None = None,
    summary: DetailHeaderSummary | None = None,
    agent_status_buckets: Mapping[str, str] | None = None,
    clan_wait_member_statuses: Mapping[str, Sequence[tuple[str, str]]] | None = None,
    tribe_wait_bindings: Mapping[tuple[object, str], TribeWaitBinding] | None = None,
    slow_tool_call_threshold_ms: int = SLOW_TOOL_CALL_THRESHOLD_MS,
    unread_agent_ids: Collection[tuple[AgentType, str, str | None]] = (),
    marked_agent_ids: Collection[tuple[AgentType, str, str | None]] = (),
    clan_snapshot: ClanSectionSnapshot | None = None,
    clan_fold_level: FoldLevel = FoldLevel.COLLAPSED,
    clan_section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    clan_neighbor_agents: tuple[Agent, ...] | None = None,
    lane_fold_level: FoldLevel | None = None,
    lane_section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    lane_neighbors: SaseAgentNeighborProjection | None = None,
    runner_capacity: RunnerCapacitySnapshot | None = None,
    member_jump_map_publisher: Callable[[MemberJumpMap], None] | None = None,
    detach_identity: bool = False,
    identity_hints: bool = True,
) -> tuple[AgentHeader, Syntax | None]:
    """Build the agent metadata section with trailing separator.

    Contains agent metadata (name, workspace, model, timestamps, etc.),
    error information, and a trailing separator line. Expensive sections are
    rendered only from ``summary`` so the builder never discovers artifacts,
    diffs, plans, or beads itself.
    """
    if agent.is_clan_container:
        from ._agent_display_clan import build_clan_detail_text

        return (
            build_clan_detail_text(
                agent,
                hint_state=hint_state,
                unread_ids=unread_agent_ids,
                snapshot=clan_snapshot,
                fold_level=clan_fold_level,
                section_fold_overrides=clan_section_fold_overrides,
                member_jump_map_publisher=member_jump_map_publisher,
                detach_identity=detach_identity,
                clan_neighbor_agents=clan_neighbor_agents,
            ),
            None,
        )

    session_turn_rows: tuple[Agent, ...] | None = None
    session_model_summary: AgentModelSummary | None = None
    if agent.is_agent_session_container_row:
        from sase.core.agent_models import AgentModelTurnFact, summarize_agent_models

        session_turn_rows = concrete_agent_session_turn_rows(agent)
        session_model_summary = summarize_agent_models(
            tuple(
                AgentModelTurnFact(
                    kind=(
                        "monitor"
                        if turn.is_monitor
                        else "gate"
                        if turn.is_gate
                        else "agent"
                        if turn.is_agent_entry
                        else "other"
                    ),
                    provider=turn.llm_provider,
                    model=turn.model,
                )
                for turn in session_turn_rows
            )
        )

    header_text = Text()
    lane_overrides = lane_section_fold_overrides or {}
    lane_scale = lane_fold_scale(agent)
    resolved_lane_fold_level = effective_fold_level(
        lane_fold_level or FoldLevel.COLLAPSED,
        lane_scale,
    )
    agent_session_fold_enabled = (
        agent.is_agent_session_container_row and lane_fold_level is not None
    )
    roster_container = agent_session_roster_container(agent)
    lane_neighbors = lane_neighbors if agent_owns_sase_agent(agent) else None
    shown_neighbor_count = 0 if lane_neighbors is None else len(lane_neighbors.rows)
    agent_session_heading_suffix: Text | None = None
    if agent_session_fold_enabled:
        agent_session_entries = agent_session_roster_entries(agent)
    elif roster_container is not None:
        agent_session_entries = agent_session_roster_entries(
            roster_container, exclude=agent
        )
        agent_session_heading_suffix = agent_session_roster_heading_suffix(
            roster_container
        )
    else:
        agent_session_entries = ()
    document_numbering = None
    if agent_session_entries or shown_neighbor_count:
        from ._member_roster import MemberJumpNumbering

        document_numbering = MemberJumpNumbering(
            total=len(agent_session_entries) + shown_neighbor_count
        )
    roster_text: Text | None = Text() if detach_identity else None
    agent_session_map = None
    from ._agent_queue_section import (
        append_runner_queue_section,
        runner_queue_selection,
    )

    queue_selection = runner_queue_selection(agent, runner_capacity)

    responsive_ranges: dict[str, tuple[int, int]] = {}
    kind_label = ""
    kind_accent = ""
    identity_text = Text()
    identity_ranges: dict[str, tuple[int, int]] = {}
    if detach_identity:
        kind_label, kind_accent = identity_kind_for_agent(agent)
        metadata = append_agent_metadata_fields(
            identity_text,
            agent,
            cheap=cheap,
            hint_state=hint_state if identity_hints else None,
            summary=summary,
            agent_status_buckets=agent_status_buckets,
            # Keep this dependency supplied by the public module so existing
            # callers can patch the cache boundary without touching internals.
            cached_bead_display=cached_bead_display,
            clan_wait_member_statuses=clan_wait_member_statuses,
            tribe_wait_bindings=tribe_wait_bindings,
            runner_queue_ahead_count=(
                queue_selection.ahead_count if queue_selection is not None else None
            ),
            responsive_ranges=identity_ranges,
            detach_identity=True,
            session_model_summary=session_model_summary,
            session_turn_rows=session_turn_rows,
        )
        if agent_session_fold_enabled:
            append_fold_header_line(
                identity_text,
                level=resolved_lane_fold_level,
                scale=AGENT_SESSION_FOLD_SCALE,
            )
        hijack_callout = build_hijack_header_callout(agent)
        if hijack_callout is not None:
            append_major_section_divider(identity_text)
            identity_text.append_text(hijack_callout)
        retention = getattr(agent, "workspace_retention", None)
        if retention is not None:
            append_major_section_divider(identity_text)
            append_section_heading(identity_text, "WORKSPACE RECOVERY")
            for line in retention.lines:
                identity_text.append(f"{line}\n", style="#D7AF5F")
    else:
        if agent.is_agent_session_container_row:
            append_kind_header(header_text, "SESSION", SESSION_IDENTITY_COLOR)
        elif agent.is_named_proc:
            append_kind_header(header_text, "NAMED PROC", _NAMED_PROC_ROW_STYLE)
        elif agent.is_agent_entry:
            append_kind_header(header_text, "AGENT TURN", _AGENT_NAME_ANNOTATION_STYLE)
        metadata = append_agent_metadata_fields(
            header_text,
            agent,
            cheap=cheap,
            hint_state=hint_state,
            summary=summary,
            agent_status_buckets=agent_status_buckets,
            # Keep this dependency supplied by the public module so existing
            # callers can patch the cache boundary without touching internals.
            cached_bead_display=cached_bead_display,
            clan_wait_member_statuses=clan_wait_member_statuses,
            tribe_wait_bindings=tribe_wait_bindings,
            runner_queue_ahead_count=(
                queue_selection.ahead_count if queue_selection is not None else None
            ),
            responsive_ranges=responsive_ranges,
            session_model_summary=session_model_summary,
            session_turn_rows=session_turn_rows,
        )
    meta_fields = metadata.meta_fields
    page_section = metadata.page_section
    wait_section = metadata.wait_section
    turn_section = metadata.turn_section

    if agent.is_agent_session_container_row:
        focus = getattr(agent, "failure_focus", None)
        if focus is not None:
            from ...models.failure_focus import failure_has_structured_causes
            from ._agent_failure_callout import (
                append_failure_callout,
                format_failure_where_session,
            )

            if not failure_has_structured_causes(focus):
                focus = None
        if focus is not None:
            append_failure_callout(
                header_text,
                focus,
                where=format_failure_where_session(focus),
                jump_number=None,
            )

    append_runner_queue_section(header_text, agent, queue_selection)

    if agent_session_fold_enabled and not detach_identity:
        append_fold_header_line(
            header_text,
            level=resolved_lane_fold_level,
            scale=AGENT_SESSION_FOLD_SCALE,
        )
    if agent_session_entries:
        agent_session_dest = roster_text if roster_text is not None else header_text
        agent_session_map = append_agent_session_member_roster(
            agent_session_dest,
            agent,
            panel_level=resolved_lane_fold_level,
            section_fold_overrides=lane_overrides,
            entries=agent_session_entries,
            numbering=document_numbering,
            fold_scale=AGENT_SESSION_FOLD_SCALE
            if agent_session_fold_enabled
            else lane_scale,
            heading_suffix=agent_session_heading_suffix,
        )

    append_legacy_parallel_members_section(header_text, agent)

    # Use-site import: the QUESTIONS mount stays out of the TUI startup
    # closure (see test_tui_app_import_stays_under_startup_budget).
    from ._agent_questions_section import append_agent_questions_section

    append_agent_questions_section(
        header_text,
        agent,
        summary=summary,
        fold_level=(
            effective_agent_session_fold_level(
                "questions",
                resolved_lane_fold_level,
                lane_overrides,
            )
            if agent_session_fold_enabled
            else None
        ),
    )

    append_agent_output_variables_section(
        header_text,
        agent,
        fold_level=(
            effective_agent_session_fold_level(
                "output-variables",
                resolved_lane_fold_level,
                lane_overrides,
            )
            if agent_session_fold_enabled
            else None
        ),
    )

    if meta_fields:
        append_major_section_divider(header_text)
        meta_level = effective_agent_session_fold_level(
            "workflow-variables",
            resolved_lane_fold_level,
            lane_overrides,
        )
        if agent_session_fold_enabled:
            append_agent_session_fold_heading(
                header_text,
                WORKFLOW_VARIABLES_SECTION_LABEL,
                section_id="workflow-variables",
                level=meta_level,
                count=len(meta_fields),
            )
        else:
            append_section_heading(
                header_text,
                WORKFLOW_VARIABLES_SECTION_LABEL,
            )
        if not agent_session_fold_enabled or meta_level != FoldLevel.COLLAPSED:
            for name, value in meta_fields:
                header_text.append(f"{name}: ", style="bold #87D7FF")
                header_text.append(f"{value}\n", style="#5FD75F")

    neighbors_map = None
    if lane_neighbors is not None:
        neighbors_dest = roster_text if roster_text is not None else header_text
        neighbors_map = append_lane_neighbors_section(
            neighbors_dest,
            projection=lane_neighbors,
            panel_level=resolved_lane_fold_level,
            scale=lane_scale,
            section_fold_overrides=lane_overrides,
            numbering=document_numbering,
            unread_agent_ids=unread_agent_ids,
            marked_identities=marked_agent_ids,
        )

    jump_map = None
    if agent_session_map is not None or neighbors_map is not None:
        from ._member_roster import merged_member_jump_map

        jump_map = merged_member_jump_map(
            agent.identity, agent_session_map, neighbors_map
        )
        if member_jump_map_publisher is not None:
            member_jump_map_publisher(jump_map)

    context_sections = append_header_context_sections(
        header_text,
        agent=agent,
        summary=summary,
        hint_state=hint_state,
        cheap=cheap,
        lane_overrides=lane_overrides,
        lane_scale=lane_scale,
        resolved_lane_fold_level=resolved_lane_fold_level,
        agent_session_fold_enabled=agent_session_fold_enabled,
        responsive_ranges=responsive_ranges,
        slow_tool_call_threshold_ms=slow_tool_call_threshold_ms,
        now_type=DateTime,
    )
    return finish_header_text(
        agent=agent,
        header_text=header_text,
        identity_text=identity_text,
        identity_ranges=identity_ranges,
        responsive_ranges=responsive_ranges,
        page_section=page_section,
        wait_section=wait_section,
        turn_section=turn_section,
        context_sections=context_sections,
        detach_identity=detach_identity,
        kind_label=kind_label,
        kind_accent=kind_accent,
        summary=summary,
        resolved_lane_fold_level=resolved_lane_fold_level,
        lane_scale=lane_scale,
        lane_overrides=lane_overrides,
        agent_session_fold_enabled=agent_session_fold_enabled,
        session_model_summary=session_model_summary,
        jump_map=jump_map,
        roster_text=roster_text,
        hint_state=hint_state,
    )
