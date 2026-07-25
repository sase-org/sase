"""Header rendering for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime as DateTime
from typing import TYPE_CHECKING

from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.tools._constants import SLOW_TOOL_CALL_THRESHOLD_MS

from ...models.agent import Agent, AgentType
from ...models.agent_bead import cached_bead_display
from ...models.agent_hoods import agent_owns_lane
from ...models.fold_scale import (
    FAMILY_FOLD_SCALE,
    effective_fold_level,
    lane_fold_scale,
)
from ...models.fold_state import FoldLevel
from ._agent_bead_section import ResponsiveBeadSection
from ._agent_display_family import (
    append_family_fold_heading,
    append_family_member_roster,
    effective_family_fold_level,
    family_roster_entries,
)
from ._agent_display_neighbors import (
    NEIGHBORS_SECTION_ID,
    append_lane_neighbors_section,
    neighbor_entry_limit,
)
from ._agent_display_header_metadata import (
    _UNASSIGNED_AGENT_NAME_DISPLAY,
    append_agent_metadata_fields,
    append_legacy_parallel_members_section,
)
from ._agent_display_header_renderable import AgentHeader, AgentHeaderRenderable
from ._agent_display_state import DetailHeaderSummary, HeaderHintState
from ._agent_output_variables import append_agent_output_variables_section
from ._agent_plan_section import ResponsivePlanSection
from ._fold_language import append_fold_header_line
from ._helpers import (
    WORKFLOW_VARIABLES_SECTION_LABEL,
    append_major_section_divider,
    append_section_heading,
)

if TYPE_CHECKING:
    from ...models._agent_clan_sections import ClanSectionSnapshot
    from ...models.agent_lane_neighbors import AgentLaneNeighborProjection
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
    slow_tool_call_threshold_ms: int = SLOW_TOOL_CALL_THRESHOLD_MS,
    unread_agent_ids: Collection[tuple[AgentType, str, str | None]] = (),
    marked_agent_ids: Collection[tuple[AgentType, str, str | None]] = (),
    clan_snapshot: ClanSectionSnapshot | None = None,
    clan_fold_level: FoldLevel = FoldLevel.COLLAPSED,
    clan_section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    lane_fold_level: FoldLevel | None = None,
    lane_section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    lane_neighbors: AgentLaneNeighborProjection | None = None,
    runner_capacity: RunnerCapacitySnapshot | None = None,
    member_jump_map_publisher: Callable[[MemberJumpMap], None] | None = None,
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
                unread_ids=unread_agent_ids,
                snapshot=clan_snapshot,
                fold_level=clan_fold_level,
                section_fold_overrides=clan_section_fold_overrides,
                member_jump_map_publisher=member_jump_map_publisher,
            ),
            None,
        )

    header_text = Text()
    lane_overrides = lane_section_fold_overrides or {}
    lane_scale = lane_fold_scale(agent)
    resolved_lane_fold_level = effective_fold_level(
        lane_fold_level or FoldLevel.COLLAPSED,
        lane_scale,
    )
    family_fold_enabled = agent.is_family_container_row and lane_fold_level is not None
    lane_neighbors = lane_neighbors if agent_owns_lane(agent) else None
    neighbors_level = effective_fold_level(
        lane_overrides.get(NEIGHBORS_SECTION_ID, resolved_lane_fold_level),
        lane_scale,
    )
    neighbors_limit = neighbor_entry_limit(neighbors_level, lane_scale)
    shown_neighbor_count = (
        0
        if lane_neighbors is None
        else (
            len(lane_neighbors.rows)
            if neighbors_limit is None
            else min(len(lane_neighbors.rows), neighbors_limit)
        )
    )
    family_entries = family_roster_entries(agent) if family_fold_enabled else ()
    document_numbering = None
    if family_entries or shown_neighbor_count:
        from ._member_roster import MemberJumpNumbering

        document_numbering = MemberJumpNumbering(
            total=len(family_entries) + shown_neighbor_count
        )
    family_map = None
    from ._agent_queue_section import (
        append_runner_queue_section,
        runner_queue_selection,
    )

    queue_selection = runner_queue_selection(agent, runner_capacity)

    meta_fields = append_agent_metadata_fields(
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
        runner_queue_ahead_count=(
            queue_selection.ahead_count if queue_selection is not None else None
        ),
    )

    append_runner_queue_section(header_text, agent, queue_selection)

    if family_fold_enabled:
        append_fold_header_line(
            header_text,
            level=resolved_lane_fold_level,
            scale=FAMILY_FOLD_SCALE,
        )
        family_map = append_family_member_roster(
            header_text,
            agent,
            panel_level=resolved_lane_fold_level,
            section_fold_overrides=lane_overrides,
            entries=family_entries,
            numbering=document_numbering,
        )

    append_legacy_parallel_members_section(header_text, agent)

    append_agent_output_variables_section(
        header_text,
        agent,
        fold_level=(
            effective_family_fold_level(
                "output-variables",
                resolved_lane_fold_level,
                lane_overrides,
            )
            if family_fold_enabled
            else None
        ),
    )

    if meta_fields:
        append_major_section_divider(header_text)
        meta_level = effective_family_fold_level(
            "workflow-variables",
            resolved_lane_fold_level,
            lane_overrides,
        )
        if family_fold_enabled:
            append_family_fold_heading(
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
        if not family_fold_enabled or meta_level != FoldLevel.COLLAPSED:
            for name, value in meta_fields:
                header_text.append(f"{name}: ", style="bold #87D7FF")
                header_text.append(f"{value}\n", style="#5FD75F")

    bead_section: ResponsiveBeadSection | None = None
    plan_section: ResponsivePlanSection | None = None
    responsive_ranges: dict[str, tuple[int, int]] = {}
    if not cheap and summary is not None:
        from ._agent_context import append_agent_context_section

        if summary.phase_bead is not None:
            bead_section = ResponsiveBeadSection(summary.phase_bead)
        if summary.associated_plan is not None:
            plan_section = ResponsivePlanSection(summary.associated_plan)
        append_agent_context_section(
            header_text,
            memory_reads=summary.memory_reads,
            skill_uses=summary.skill_uses,
            opened_workspaces=summary.opened_workspaces,
            bead_section=bead_section,
            plan_section=plan_section,
            agent=agent,
            delta_entries=summary.delta_entries,
            linked_delta_groups=summary.linked_delta_groups,
            artifact_file_paths=summary.artifact_file_paths,
            hint_state=hint_state,
            responsive_ranges=responsive_ranges,
            fold_level=(resolved_lane_fold_level if family_fold_enabled else None),
            section_fold_overrides=lane_overrides,
        )

        from ._agent_slow_tools import append_slow_tool_calls_section

        append_slow_tool_calls_section(
            header_text,
            sources=summary.slow_tool_sources,
            agent=agent,
            now=DateTime.now(),
            hint_state=hint_state,
            threshold_ms=slow_tool_call_threshold_ms,
            fold_level=(
                effective_family_fold_level(
                    "slow-tool-calls",
                    resolved_lane_fold_level,
                    lane_overrides,
                )
                if family_fold_enabled
                else None
            ),
        )

    is_failed = agent.display_status == "FAILED"
    if agent.error_message or is_failed:
        header_text.append("\n")
        error_level = effective_family_fold_level(
            "error",
            resolved_lane_fold_level,
            lane_overrides,
        )
        if family_fold_enabled:
            append_family_fold_heading(
                header_text,
                "ERROR",
                style="bold #FF5F5F underline",
                section_id="error",
                level=error_level,
                count=1,
            )
        else:
            append_section_heading(
                header_text,
                "ERROR",
                style="bold #FF5F5F underline",
                section_id="error",
            )
        error_message = agent.error_message or "Runner failed without error details."
        if not family_fold_enabled or error_level != FoldLevel.COLLAPSED:
            header_text.append(f"{error_message}\n", style="bold #FF5F5F")
    if agent.output_path and is_failed:
        header_text.append("Output: ", style="bold #87D7FF")
        header_text.append(f"{agent.output_path}\n", style="dim")

    neighbors_map = None
    if lane_neighbors is not None:
        neighbors_map = append_lane_neighbors_section(
            header_text,
            projection=lane_neighbors,
            panel_level=resolved_lane_fold_level,
            scale=lane_scale,
            section_fold_overrides=lane_overrides,
            numbering=document_numbering,
            unread_agent_ids=unread_agent_ids,
            marked_identities=marked_agent_ids,
        )

    if member_jump_map_publisher is not None and (
        family_map is not None or neighbors_map is not None
    ):
        from ._member_roster import merged_member_jump_map

        member_jump_map_publisher(
            merged_member_jump_map(agent.identity, family_map, neighbors_map)
        )

    error_tb_syntax: Syntax | None = None
    if agent.error_traceback:
        error_tb_syntax = Syntax(
            agent.error_traceback,
            "pytb",
            theme="monokai",
            word_wrap=True,
        )

    header_text.append("\n")
    header_text.append("\u2500" * 50 + "\n", style="dim")
    header_text.append("\n")

    responsive_sections: list[
        tuple[int, int, ResponsiveBeadSection | ResponsivePlanSection]
    ] = []
    if bead_section is not None and "BEAD" in responsive_ranges:
        start, end = responsive_ranges["BEAD"]
        responsive_sections.append((start, end, bead_section))
    if plan_section is not None and "PLAN" in responsive_ranges:
        start, end = responsive_ranges["PLAN"]
        responsive_sections.append((start, end, plan_section))
    if responsive_sections:
        responsive_sections.sort(key=lambda section: section[0])
        return (
            AgentHeaderRenderable(
                header_text,
                tuple(responsive_sections),
            ),
            error_tb_syntax,
        )
    return header_text, error_tb_syntax
