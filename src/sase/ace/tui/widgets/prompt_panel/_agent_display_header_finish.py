"""Finish agent header error, responsive-section, and detached-identity rendering."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from rich.syntax import Syntax
from rich.text import Text

from ...models.agent import Agent
from ...models.fold_scale import AGENT_SESSION_FOLD_SCALE, FoldScale
from ...models.fold_state import FoldLevel
from ._agent_bead_section import ResponsiveBeadSection
from ._agent_bead_touches import BEAD_TOUCHES_SECTION_ID, ResponsiveBeadTouchesSection
from ._agent_display_agent_session import (
    append_agent_session_fold_heading,
    effective_agent_session_fold_level,
)
from ._agent_display_header_context import HeaderContextSections
from ._agent_display_header_renderable import AgentHeader, AgentHeaderRenderable
from ._agent_display_state import DetailHeaderSummary, HeaderHintState
from ._agent_page_section import (
    AGENT_PAGE_SECTION_ID,
    ResponsiveAgentPageSection,
)
from ._agent_plan_section import ResponsivePlanSection
from ._agent_turn_section import TURN_SECTION_ID, ResponsiveTurnSection
from ._agent_slow_tools_detail import ResponsiveSlowToolCallsSection
from ._agent_wait_section import WAIT_SECTION_ID, ResponsiveWaitSection
from ._helpers import append_section_heading
from ._identity_header import IdentityHeader, strip_leading_document_chrome
from ._identity_header_compact import build_agent_compact_lines

if TYPE_CHECKING:
    from ...models._agent_clan_sections import ClanSectionSnapshot
    from ...models.agent_runner_slots import RunnerCapacitySnapshot
    from ...models.sase_agent_neighbors import SaseAgentNeighborProjection
    from ._member_roster import MemberJumpMap
    from sase.core.agent_models import AgentModelSummary


def finish_header_text(
    *,
    agent: Agent,
    header_text: Text,
    identity_text: Text,
    identity_ranges: dict[str, tuple[int, int]],
    responsive_ranges: dict[str, tuple[int, int]],
    page_section: ResponsiveAgentPageSection | None,
    wait_section: ResponsiveWaitSection | None,
    turn_section: ResponsiveTurnSection | None,
    context_sections: HeaderContextSections,
    detach_identity: bool,
    kind_label: str,
    kind_accent: str,
    summary: DetailHeaderSummary | None,
    resolved_lane_fold_level: FoldLevel,
    lane_scale: FoldScale,
    lane_overrides: Mapping[str, FoldLevel],
    agent_session_fold_enabled: bool,
    session_model_summary: AgentModelSummary | None,
    jump_map: MemberJumpMap | None,
    roster_text: Text | None,
    hint_state: HeaderHintState | None,
) -> tuple[AgentHeader, Syntax | None]:
    """Append error/footer content and assemble the final header renderable."""
    is_failed = agent.display_status == "FAILED"
    if agent.error_message or is_failed:
        header_text.append("\n")
        error_level = effective_agent_session_fold_level(
            "error",
            resolved_lane_fold_level,
            lane_overrides,
        )
        if agent_session_fold_enabled:
            append_agent_session_fold_heading(
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
        if not agent_session_fold_enabled or error_level != FoldLevel.COLLAPSED:
            header_text.append(f"{error_message}\n", style="bold #FF5F5F")
    if agent.output_path and is_failed:
        header_text.append("Output: ", style="bold #87D7FF")
        header_text.append(f"{agent.output_path}\n", style="dim")

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

    if detach_identity:
        identity_sections = _assemble_responsive_sections(
            identity_ranges,
            page_section,
            wait_section,
            turn_section,
            None,
            None,
            None,
            None,
        )
        expanded: AgentHeader
        if identity_sections:
            expanded = AgentHeaderRenderable(identity_text, identity_sections)
        else:
            expanded = identity_text
        identity = IdentityHeader(
            kind_label=kind_label,
            accent=kind_accent,
            expanded=expanded,
            compact=build_agent_compact_lines(
                agent=agent,
                summary=summary,
                wait_section=wait_section,
                turn_section=turn_section,
                fold_level=resolved_lane_fold_level
                if agent_session_fold_enabled
                else None,
                fold_scale=AGENT_SESSION_FOLD_SCALE
                if agent_session_fold_enabled
                else None,
            ),
            model_summary=session_model_summary,
        )
        body_text, removed_chars = strip_leading_document_chrome(header_text)
        shifted_ranges = {
            key: (max(0, start - removed_chars), max(0, end - removed_chars))
            for key, (start, end) in responsive_ranges.items()
        }
        body_sections = _assemble_responsive_sections(
            shifted_ranges,
            None,
            None,
            None,
            context_sections.bead,
            context_sections.plan,
            context_sections.slow_tools,
            context_sections.bead_touches,
        )
        carrier = AgentHeaderRenderable(
            body_text,
            body_sections,
            identity_header=identity,
        )
        if (
            hint_state is None
            and jump_map is not None
            and (jump_map.targets or jump_map.sections)
        ):
            from ._member_roster import detached_roster_text

            roster = (
                detached_roster_text(roster_text) if roster_text is not None else None
            )
            carrier.with_member_jump_map(jump_map, roster=roster)
        return carrier, error_tb_syntax

    responsive_sections = _assemble_responsive_sections(
        responsive_ranges,
        page_section,
        wait_section,
        turn_section,
        context_sections.bead,
        context_sections.plan,
        context_sections.slow_tools,
        context_sections.bead_touches,
    )
    if responsive_sections:
        return AgentHeaderRenderable(header_text, responsive_sections), error_tb_syntax
    return header_text, error_tb_syntax


def _assemble_responsive_sections(
    responsive_ranges: dict[str, tuple[int, int]],
    page_section: ResponsiveAgentPageSection | None,
    wait_section: ResponsiveWaitSection | None,
    turn_section: ResponsiveTurnSection | None,
    bead_section: ResponsiveBeadSection | None,
    plan_section: ResponsivePlanSection | None,
    slow_tool_section: ResponsiveSlowToolCallsSection | None,
    bead_touches_section: ResponsiveBeadTouchesSection | None,
) -> tuple[
    tuple[
        int,
        int,
        ResponsiveAgentPageSection
        | ResponsiveBeadSection
        | ResponsiveBeadTouchesSection
        | ResponsiveTurnSection
        | ResponsivePlanSection
        | ResponsiveSlowToolCallsSection
        | ResponsiveWaitSection,
    ],
    ...,
]:
    """Order responsive ranges and sections into a renderable section map."""
    responsive_sections: list[
        tuple[
            int,
            int,
            ResponsiveAgentPageSection
            | ResponsiveBeadSection
            | ResponsiveBeadTouchesSection
            | ResponsiveTurnSection
            | ResponsivePlanSection
            | ResponsiveSlowToolCallsSection
            | ResponsiveWaitSection,
        ]
    ] = []
    if page_section is not None and AGENT_PAGE_SECTION_ID in responsive_ranges:
        start, end = responsive_ranges[AGENT_PAGE_SECTION_ID]
        responsive_sections.append((start, end, page_section))
    if wait_section is not None and WAIT_SECTION_ID in responsive_ranges:
        start, end = responsive_ranges[WAIT_SECTION_ID]
        responsive_sections.append((start, end, wait_section))
    if turn_section is not None and TURN_SECTION_ID in responsive_ranges:
        start, end = responsive_ranges[TURN_SECTION_ID]
        responsive_sections.append((start, end, turn_section))
    if bead_section is not None and "BEAD" in responsive_ranges:
        start, end = responsive_ranges["BEAD"]
        responsive_sections.append((start, end, bead_section))
    if plan_section is not None and "PLAN" in responsive_ranges:
        start, end = responsive_ranges["PLAN"]
        responsive_sections.append((start, end, plan_section))
    if (
        bead_touches_section is not None
        and BEAD_TOUCHES_SECTION_ID in responsive_ranges
    ):
        start, end = responsive_ranges[BEAD_TOUCHES_SECTION_ID]
        responsive_sections.append((start, end, bead_touches_section))
    if slow_tool_section is not None and "slow-tool-calls" in responsive_ranges:
        start, end = responsive_ranges["slow-tool-calls"]
        responsive_sections.append((start, end, slow_tool_section))
    responsive_sections.sort(key=lambda section: section[0])
    return tuple(responsive_sections)
