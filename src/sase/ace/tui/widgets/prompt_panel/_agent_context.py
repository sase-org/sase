"""SASE CONTEXT section rendering for the prompt panel header."""

from __future__ import annotations

from collections.abc import Callable

from rich.text import Text

from sase.ace.changespec.models import DeltaEntry
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent

from ...models.agent import Agent
from ..file_panel._linked_deltas import LinkedDeltaGroup
from ._agent_artifacts import AgentArtifactPath
from ._agent_artifacts_lane import append_agent_artifacts_lane
from ._agent_memory_reads import append_agent_memory_reads_section
from ._agent_opened_workspaces import append_agent_opened_workspaces_section
from ._agent_plan_section import ResponsivePlanSection
from ._agent_skill_uses import append_agent_skills_section
from ._agent_display_state import HeaderHintState
from ._helpers import append_major_section_divider, append_section_heading

_COLOR_HEADER = "bold #D7AF5F underline"
CONTEXT_LANE_ORDER = ("PLAN", "MEMORY", "SKILLS", "WORKSPACES", "ARTIFACTS")


def append_agent_context_section(
    text: Text,
    *,
    memory_reads: tuple[MemoryReadDisplayEvent, ...] = (),
    skill_uses: tuple[SkillUseDisplayEvent, ...] = (),
    opened_workspaces: tuple[OpenedWorkspaceDisplayEvent, ...] = (),
    plan_section: ResponsivePlanSection | None = None,
    agent: Agent | None = None,
    delta_entries: list[DeltaEntry] | None = None,
    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = (),
    artifact_paths: list[AgentArtifactPath] | None = None,
    hint_state: HeaderHintState | None = None,
) -> tuple[int, int] | None:
    """Append present SASE CONTEXT lanes in the declared narrative order."""

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
            artifact_paths=artifact_paths,
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
    append_section_heading(text, "SASE CONTEXT", style=_COLOR_HEADER)
    plan_range: tuple[int, int] | None = None
    for index, (label, lane) in enumerate(rendered_lanes):
        if index:
            text.append("\n")
        lane_start = len(text)
        text.append_text(lane)
        if label == "PLAN":
            plan_range = (lane_start, len(text))
    return plan_range
