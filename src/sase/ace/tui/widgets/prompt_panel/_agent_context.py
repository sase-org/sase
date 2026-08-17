"""SASE CONTEXT section rendering for the prompt panel header."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from rich.text import Text

from sase.ace.patch.models import DeltaEntry
from sase.ace.tui.glossary_reads import GlossaryReadDisplayEvent
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent

from ...models.agent import Agent
from ...models.fold_state import FoldLevel
from ..file_panel._linked_deltas import LinkedDeltaGroup
from ._artifact_files import ArtifactFilePath
from ._agent_artifacts_lane import append_agent_artifacts_lane
from ._agent_bead_section import BEAD_SECTION_ID, ResponsiveBeadSection
from ._agent_context_common import (
    COLOR_ARTIFACTS_SUBHEADER,
    COLOR_BEAD_SUBHEADER,
    COLOR_GLOSSARY_SUBHEADER,
    COLOR_MEMORY_SUBHEADER,
    COLOR_PLAN_SUBHEADER,
    COLOR_SKILLS_SUBHEADER,
    COLOR_TRUNCATION,
    COLOR_WORKSPACE_SUBHEADER,
    append_context_lane_header,
)
from ._agent_glossary_reads import append_agent_glossary_reads_section
from ._agent_memory_reads import append_agent_memory_reads_section
from ._agent_opened_workspaces import append_agent_opened_workspaces_section
from ._agent_plan_section import ResponsivePlanSection
from ._agent_skill_uses import append_agent_skills_section
from ._agent_display_state import DetailContextLane, HeaderHintState
from ._helpers import append_major_section_divider, append_section_heading

_COLOR_HEADER = "bold #D7AF5F underline"
# The authored plan is the agent's stated intent; keep the bead context directly
# beneath it when both lanes are present.
CONTEXT_LANE_ORDER = (
    "PLAN",
    "BEAD",
    "ARTIFACTS",
    "MEMORY",
    "GLOSSARY",
    "SKILLS",
    "WORKSPACES",
)

# Which resolved `DetailContextLane` backs each `CONTEXT_LANE_ORDER` label.
# PLAN and BEAD deliberately share `plan-bead` (bead sase-l6.3): if that
# lane is still resolving, both render their own pending row rather than
# trying to merge into one, since which of the two will end up with
# content is not known until the lane actually lands.
_LANE_LABEL_BACKING: dict[str, DetailContextLane] = {
    "PLAN": "plan-bead",
    "BEAD": "plan-bead",
    "ARTIFACTS": "artifacts",
    "MEMORY": "memory",
    "GLOSSARY": "glossary",
    "SKILLS": "skills",
    "WORKSPACES": "workspaces",
}
_LANE_LABEL_PENDING_STYLE: dict[str, str] = {
    "PLAN": COLOR_PLAN_SUBHEADER,
    "BEAD": COLOR_BEAD_SUBHEADER,
    "ARTIFACTS": COLOR_ARTIFACTS_SUBHEADER,
    "MEMORY": COLOR_MEMORY_SUBHEADER,
    "GLOSSARY": COLOR_GLOSSARY_SUBHEADER,
    "SKILLS": COLOR_SKILLS_SUBHEADER,
    "WORKSPACES": COLOR_WORKSPACE_SUBHEADER,
}
_LANE_PENDING_DETAIL = "resolving…"


def append_agent_context_section(
    text: Text,
    *,
    memory_reads: tuple[MemoryReadDisplayEvent, ...] = (),
    glossary_reads: tuple[GlossaryReadDisplayEvent, ...] = (),
    skill_uses: tuple[SkillUseDisplayEvent, ...] = (),
    opened_workspaces: tuple[OpenedWorkspaceDisplayEvent, ...] = (),
    bead_section: ResponsiveBeadSection | None = None,
    plan_section: ResponsivePlanSection | None = None,
    agent: Agent | None = None,
    delta_entries: list[DeltaEntry] | None = None,
    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = (),
    artifact_file_paths: list[ArtifactFilePath] | None = None,
    hint_state: HeaderHintState | None = None,
    responsive_ranges: dict[str, tuple[int, int]] | None = None,
    fold_level: FoldLevel | None = None,
    section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    ready_lanes: frozenset[DetailContextLane] | None = None,
) -> tuple[int, int] | None:
    """Append present SASE CONTEXT lanes in the declared narrative order.

    ``ready_lanes`` distinguishes a lane that has not resolved yet from one
    that resolved to nothing (bead sase-l6.4): when it is not ``None``, a
    label whose backing lane is absent renders a dim, non-interactive
    "resolving…" row instead of being silently skipped, so streamed lanes
    render progressively without the section visibly reshuffling once the
    rest land. Passing ``None`` keeps the legacy behavior of treating "no
    data" and "not requested" identically.
    """

    def append_bead_lane(lane: Text) -> None:
        if bead_section is None:
            return
        actual_path = bead_section.summary.actual_plan_path
        if (
            hint_state is not None
            and bead_section.hint_number is None
            and actual_path is not None
        ):
            hint_number = hint_state.hint_counter
            hint_state.hint_mappings[hint_number] = actual_path
            hint_state.hint_counter += 1
            bead_section.hint_number = hint_number
        lane.append_text(bead_section.logical_text)

    def append_plan_lane(lane: Text) -> None:
        if plan_section is None:
            return
        if hint_state is not None and plan_section.hint_number is None:
            hint_number = hint_state.hint_counter
            hint_state.hint_mappings[hint_number] = plan_section.summary.actual_path
            hint_state.hint_counter += 1
            plan_section.hint_number = hint_number
        lane.append_text(plan_section.logical_text)

    lane_renderers: dict[str, Callable[[Text], None]] = {
        "BEAD": append_bead_lane,
        "PLAN": append_plan_lane,
        "MEMORY": lambda lane: append_agent_memory_reads_section(
            lane,
            events=memory_reads,
            hint_state=hint_state,
        ),
        "GLOSSARY": lambda lane: append_agent_glossary_reads_section(
            lane,
            events=glossary_reads,
            hint_state=hint_state,
        ),
        "SKILLS": lambda lane: append_agent_skills_section(
            lane,
            events=skill_uses,
        ),
        "WORKSPACES": lambda lane: append_agent_opened_workspaces_section(
            lane,
            events=opened_workspaces,
        ),
        "ARTIFACTS": lambda lane: append_agent_artifacts_lane(
            lane,
            agent=agent,
            delta_entries=delta_entries,
            linked_delta_groups=linked_delta_groups,
            artifact_file_paths=artifact_file_paths,
            hint_state=hint_state,
        ),
    }
    rendered_lanes: list[tuple[str, Text]] = []
    for label in CONTEXT_LANE_ORDER:
        lane = Text()
        if ready_lanes is not None and _LANE_LABEL_BACKING[label] not in ready_lanes:
            append_context_lane_header(
                lane,
                label,
                label_style=_LANE_LABEL_PENDING_STYLE[label],
                details=_LANE_PENDING_DETAIL,
                details_style=COLOR_TRUNCATION,
            )
        else:
            lane_renderers[label](lane)
        if lane:
            rendered_lanes.append((label, lane))
    if not rendered_lanes:
        return None

    append_major_section_divider(text)
    family_lane_levels: dict[str, FoldLevel] | None = None
    if fold_level is None:
        append_section_heading(text, "SASE CONTEXT", style=_COLOR_HEADER)
    else:
        from ._agent_display_family import (
            effective_family_fold_level,
        )
        from ._fold_language import append_fold_glyph

        text.append("SASE CONTEXT", style=_COLOR_HEADER)
        text.append(f" · {len(rendered_lanes)}\n", style="dim")
        lane_ids = {
            "BEAD": BEAD_SECTION_ID,
            "PLAN": "plan",
            "ARTIFACTS": "artifacts",
            "MEMORY": "memory-reads",
            "GLOSSARY": "glossary-reads",
            "SKILLS": "skill-uses",
            "WORKSPACES": "opened-workspaces",
        }
        family_lane_levels = {
            label: effective_family_fold_level(
                lane_ids[label],
                fold_level,
                section_fold_overrides,
            )
            for label, _lane in rendered_lanes
        }
    plan_range: tuple[int, int] | None = None
    for index, (label, lane) in enumerate(rendered_lanes):
        if index:
            text.append("\n")
        if family_lane_levels is not None:
            lane_level = family_lane_levels[label]
            line_end = lane.plain.find("\n")
            if line_end < 0:
                line_end = len(lane)
            source_heading = lane[:line_end]
            heading = Text()
            append_fold_glyph(heading, lane_level)
            heading.append_text(source_heading[2:])
            section_id = {
                "BEAD": BEAD_SECTION_ID,
                "PLAN": "plan",
                "ARTIFACTS": "artifacts",
                "MEMORY": "memory-reads",
                "GLOSSARY": "glossary-reads",
                "SKILLS": "skill-uses",
                "WORKSPACES": "opened-workspaces",
            }[label]
            append_section_heading(text, heading, section_id=section_id)
            if lane_level != FoldLevel.COLLAPSED and line_end < len(lane):
                text.append_text(lane[line_end + 1 :])
            continue
        lane_start = len(text)
        text.append_text(lane)
        if responsive_ranges is not None and label in {"BEAD", "PLAN"}:
            responsive_ranges[label] = (lane_start, len(text))
        if label == "PLAN":
            plan_range = (lane_start, len(text))
    return plan_range
