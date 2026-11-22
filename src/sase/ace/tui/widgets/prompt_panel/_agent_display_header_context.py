"""Build the responsive context sections attached to an agent header."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text

from ...models.agent import Agent
from ...models.fold_scale import FoldScale, effective_fold_level
from ...models.fold_state import FoldLevel
from ._agent_bead_section import (
    BEAD_SECTION_ID,
    ResponsiveBeadSection,
    bead_detail_level,
)
from ._agent_bead_touches import ResponsiveBeadTouchesSection
from ._agent_display_state import DetailHeaderSummary, HeaderHintState
from ._agent_plan_section import ResponsivePlanSection
from ._agent_slow_tools_detail import ResponsiveSlowToolCallsSection

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class HeaderContextSections:
    """Responsive section objects created while appending header context."""

    bead: ResponsiveBeadSection | None = None
    plan: ResponsivePlanSection | None = None
    slow_tools: ResponsiveSlowToolCallsSection | None = None
    bead_touches: ResponsiveBeadTouchesSection | None = None


def append_header_context_sections(
    text: Text,
    *,
    agent: Agent,
    summary: DetailHeaderSummary | None,
    hint_state: HeaderHintState | None,
    cheap: bool,
    lane_overrides: Mapping[str, FoldLevel],
    lane_scale: FoldScale,
    resolved_lane_fold_level: FoldLevel,
    agent_session_fold_enabled: bool,
    responsive_ranges: dict[str, tuple[int, int]],
    slow_tool_call_threshold_ms: int,
    now_type: type[datetime],
) -> HeaderContextSections:
    """Append context/slow-tool content and return its responsive section data."""
    bead_section: ResponsiveBeadSection | None = None
    plan_section: ResponsivePlanSection | None = None
    slow_tool_section: ResponsiveSlowToolCallsSection | None = None
    bead_touches_section: ResponsiveBeadTouchesSection | None = None
    if summary is not None:
        # SASE CONTEXT renders whenever there is a summary at all, cheap or
        # not: `append_agent_context_section` already distinguishes ready
        # lanes from pending ones via `ready_lanes`, so the immediate
        # zero-I/O path (bead sase-l6.5) and the debounced full path share
        # one renderer instead of the cheap flag hiding the section outright.
        from ._agent_context import append_agent_context_section

        if summary.bead_summary is not None:
            bead_section = ResponsiveBeadSection(
                summary.bead_summary,
                detail=bead_detail_level(
                    effective_fold_level(
                        lane_overrides.get(
                            BEAD_SECTION_ID,
                            resolved_lane_fold_level,
                        ),
                        lane_scale,
                    ),
                    lane_scale,
                ),
            )
        if summary.associated_plan is not None:
            plan_section = ResponsivePlanSection(summary.associated_plan)
        bead_touches_captured: list[ResponsiveBeadTouchesSection] = []
        append_agent_context_section(
            text,
            memory_reads=summary.memory_reads,
            memory_version_chips=summary.memory_version_chips,
            memory_version_pins=summary.memory_version_pins,
            memory_launch_row=summary.memory_launch_row,
            memory_launch_pin=summary.memory_launch_pin,
            glossary_reads=summary.glossary_reads,
            skill_uses=summary.skill_uses,
            opened_workspaces=summary.opened_workspaces,
            bead_section=bead_section,
            plan_section=plan_section,
            agent=agent,
            delta_entries=summary.delta_entries,
            linked_delta_groups=summary.linked_delta_groups,
            artifact_file_paths=summary.artifact_file_paths,
            artifact_reads=summary.artifact_reads,
            bead_touch_entries=summary.bead_touch_entries,
            hint_state=hint_state,
            responsive_ranges=responsive_ranges,
            fold_level=(
                resolved_lane_fold_level if agent_session_fold_enabled else None
            ),
            section_fold_overrides=lane_overrides,
            ready_lanes=summary.ready_lanes,
            bead_touches_section_out=bead_touches_captured,
        )
        bead_touches_section = (
            bead_touches_captured[0] if bead_touches_captured else None
        )

    if not cheap and summary is not None:
        # Slow tool calls is not a SASE CONTEXT lane and is not guaranteed
        # zero-I/O (bead sase-l6 trace: up to ~114 ms cold), so it stays
        # behind the debounced path rather than joining the immediate paint.
        from ._agent_slow_tools import (
            append_slow_tool_calls_section,
            resolve_slow_tool_overflow_keys,
        )

        try:
            overflow_keys = resolve_slow_tool_overflow_keys()
        except Exception:
            overflow_keys = {}
        try:
            from ...tool_runs.links import slow_suffixes_for_agent_sources

            tool_run_suffixes = (
                slow_suffixes_for_agent_sources(
                    agent,
                    summary.slow_tool_sources,
                    getattr(summary, "tool_run_summary", None),
                )
                or None
            )
        except Exception:
            tool_run_suffixes = None
        slow_tool_section = append_slow_tool_calls_section(
            text,
            sources=summary.slow_tool_sources,
            agent=agent,
            now=now_type.now(),
            hint_state=hint_state,
            threshold_ms=slow_tool_call_threshold_ms,
            panel_level=resolved_lane_fold_level,
            scale=lane_scale,
            section_fold_overrides=lane_overrides,
            responsive_ranges=responsive_ranges,
            overflow_hint_keys=overflow_keys,
            tool_run_suffixes=tool_run_suffixes,
        )

    return HeaderContextSections(
        bead=bead_section,
        plan=plan_section,
        slow_tools=slow_tool_section,
        bead_touches=bead_touches_section,
    )
