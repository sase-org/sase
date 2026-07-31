"""Fold-aware tribe metadata documents for whole-panel focus."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from rich.text import Text

from ...models.agent_tribe_summary import AgentTribeSummarySnapshot
from ...models.fold_scale import TRIBE_FOLD_SCALE
from ...models.fold_state import FoldLevel
from ._agent_display_tribe_common import (
    SECTIONS,
    TRIBE_IDENTITY_COLOR as TRIBE_IDENTITY_COLOR,
    effective_level,
)
from ._agent_display_tribe_header import append_tribe_header
from ._agent_display_tribe_roster import (
    entry_target_heading_suffix,
    tribe_roster_entries,
)
from ._agent_display_tribe_sections import (
    append_attention,
    append_errors,
    append_replies,
    append_runtime_statistics,
    append_slow_tool_calls,
    append_variables,
)
from ._agent_tribe_aggregation import (
    TribeEnrichmentSection,
    TribeSectionSnapshot,
)
from ._fold_language import append_scanning_tail
from ._member_roster import MemberJumpMap, append_member_roster


def tribe_enrichment_sections_for_fold_state(
    panel_level: FoldLevel,
    overrides: Mapping[str, FoldLevel] | None = None,
) -> frozenset[TribeEnrichmentSection]:
    """Return off-thread sections needed by the effective tribe folds."""
    fold_overrides = overrides or {}
    required: set[TribeEnrichmentSection] = {"replies", "slow-tool-calls"}
    if (
        effective_level(
            SECTIONS.runtime_statistics,
            panel_level,
            fold_overrides,
        )
        is FoldLevel.EXHAUSTIVE
    ):
        required.add("runtime-statistics")
    return frozenset(required)


def _has_pending_enrichment(
    snapshot: TribeSectionSnapshot | None,
    required: frozenset[TribeEnrichmentSection],
) -> bool:
    disk = snapshot.disk if snapshot is not None else None
    for section in required:
        if section == "runtime-statistics":
            if snapshot is None or not snapshot.runtime_statistics_loaded:
                return True
        elif disk is None or section not in disk.loaded_sections:
            return True
    return False


def build_tribe_detail_text(
    snapshot: AgentTribeSummarySnapshot,
    *,
    section_snapshot: TribeSectionSnapshot | None = None,
    fold_level: FoldLevel = FoldLevel.COLLAPSED,
    section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    member_jump_map_publisher: Callable[[MemberJumpMap], None] | None = None,
    cheap: bool = False,
) -> Text:
    """Build a fold-aware tribe document without filesystem access."""
    overrides = section_fold_overrides or {}
    required = tribe_enrichment_sections_for_fold_state(fold_level, overrides)
    text = Text()
    append_tribe_header(text, snapshot, fold_level)
    if cheap:
        return text

    append_attention(
        text,
        snapshot.attention,
        level=effective_level(SECTIONS.attention, fold_level, overrides),
    )
    jump_map = append_member_roster(
        text,
        container_identity=snapshot.container_identity,
        entries=tribe_roster_entries(snapshot),
        title="TRIBE MEMBERS",
        accent=TRIBE_IDENTITY_COLOR,
        panel_level=fold_level,
        section_fold_overrides=overrides,
        fold_scale=TRIBE_FOLD_SCALE,
        section_id=SECTIONS.members,
        member_anchor_prefix="tribe:member:",
        children_from_level=FoldLevel.FULLY_EXPANDED,
        full_annotations_from_level=FoldLevel.EXHAUSTIVE,
        entry_cursor=not snapshot.panel_collapsed,
        heading_suffix=entry_target_heading_suffix(snapshot),
    )
    if member_jump_map_publisher is not None:
        member_jump_map_publisher(jump_map)

    append_errors(
        text,
        snapshot.errors,
        level=effective_level(SECTIONS.errors, fold_level, overrides),
    )
    append_variables(
        text,
        snapshot.output_variables,
        title="OUTPUT VARIABLES",
        section_id=SECTIONS.output_variables,
        level=effective_level(SECTIONS.output_variables, fold_level, overrides),
    )
    append_variables(
        text,
        snapshot.workflow_variables,
        title="WORKFLOW VARIABLES",
        section_id=SECTIONS.workflow_variables,
        level=effective_level(SECTIONS.workflow_variables, fold_level, overrides),
    )
    append_replies(
        text,
        section_snapshot,
        level=effective_level(SECTIONS.replies, fold_level, overrides),
    )
    append_slow_tool_calls(
        text,
        section_snapshot,
        level=effective_level(SECTIONS.slow_tool_calls, fold_level, overrides),
    )
    append_runtime_statistics(
        text,
        section_snapshot,
        level=effective_level(
            SECTIONS.runtime_statistics,
            fold_level,
            overrides,
        ),
    )
    if _has_pending_enrichment(section_snapshot, required):
        append_scanning_tail(text)
    return text


__all__ = [
    "TRIBE_IDENTITY_COLOR",
    "build_tribe_detail_text",
    "tribe_enrichment_sections_for_fold_state",
]
