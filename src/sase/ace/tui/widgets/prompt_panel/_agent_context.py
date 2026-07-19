"""SASE CONTEXT section rendering for the prompt panel header."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from rich.text import Text

from sase.ace.changespec.models import DeltaEntry
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent

from ...models.agent import Agent
from ...models.fold_state import FoldLevel
from ..file_panel._linked_deltas import LinkedDeltaGroup
from ._artifact_files import ArtifactFilePath
from ._agent_artifacts_lane import append_agent_artifacts_lane
from ._agent_bead_section import ResponsiveBeadSection
from ._agent_memory_reads import append_agent_memory_reads_section
from ._agent_opened_workspaces import append_agent_opened_workspaces_section
from ._agent_plan_section import ResponsivePlanSection
from ._agent_skill_uses import append_agent_skills_section
from ._agent_display_state import HeaderHintState
from ._helpers import append_major_section_divider, append_section_heading

_COLOR_HEADER = "bold #D7AF5F underline"
CONTEXT_LANE_ORDER = (
    "BEAD",
    "PLAN",
    "ARTIFACTS",
    "MEMORY",
    "SKILLS",
    "WORKSPACES",
)


def append_agent_context_section(
    text: Text,
    *,
    memory_reads: tuple[MemoryReadDisplayEvent, ...] = (),
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
) -> tuple[int, int] | None:
    """Append present SASE CONTEXT lanes in the declared narrative order."""

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
            "BEAD": "bead",
            "PLAN": "plan",
            "ARTIFACTS": "artifacts",
            "MEMORY": "memory-reads",
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
                "BEAD": "bead",
                "PLAN": "plan",
                "ARTIFACTS": "artifacts",
                "MEMORY": "memory-reads",
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
