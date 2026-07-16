"""Ranked ARTIFACTS lane for the prompt panel's SASE CONTEXT section."""

from __future__ import annotations

from rich.text import Text

from sase.ace.changespec.models import DeltaEntry

from ...models.agent import Agent
from ..file_panel._linked_deltas import LinkedDeltaGroup
from ._agent_artifacts import AgentArtifactPath, append_agent_artifact_paths
from ._agent_commits import (
    agent_commit_groups,
    append_agent_commit_groups,
    count_agent_commit_groups,
)
from ._agent_context_common import (
    COLOR_ARTIFACTS_SUBHEADER,
    COLOR_SUMMARY,
    append_context_lane_header,
    count_phrase,
)
from ._agent_deltas import (
    append_agent_deltas_section,
    visible_agent_delta_entries,
    visible_agent_linked_delta_groups,
)
from ._agent_display_state import HeaderHintState


def append_agent_artifacts_lane(
    text: Text,
    *,
    agent: Agent | None = None,
    delta_entries: list[DeltaEntry] | None = None,
    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = (),
    artifact_paths: list[AgentArtifactPath] | None = None,
    hint_state: HeaderHintState | None = None,
) -> None:
    """Append Commits, Deltas, and Artifacts as one ranked output lane."""
    commit_groups = agent_commit_groups(agent) if agent is not None else ()
    deltas = visible_agent_delta_entries(delta_entries or ())
    linked_groups = visible_agent_linked_delta_groups(linked_delta_groups)
    artifacts = artifact_paths or []

    details: list[str] = []
    commit_count = count_agent_commit_groups(commit_groups)
    if commit_count:
        details.append(count_phrase(commit_count, "commit"))
    delta_count = len(deltas) + sum(len(group.entries) for group in linked_groups)
    if delta_count:
        details.append(count_phrase(delta_count, "file"))
    if artifacts:
        details.append(count_phrase(len(artifacts), "artifact"))
    if not details:
        return

    append_context_lane_header(
        text,
        "ARTIFACTS",
        label_style=COLOR_ARTIFACTS_SUBHEADER,
        details=" · ".join(details),
    )
    if commit_groups:
        text.append("  Commits:\n", style=COLOR_SUMMARY)
        append_agent_commit_groups(
            text,
            commit_groups,
            hint_state=hint_state,
            indent="  ",
        )
    if deltas or linked_groups:
        append_agent_deltas_section(
            text,
            delta_entries=deltas,
            linked_delta_groups=linked_groups,
            hint_state=hint_state,
            indent="  ",
            header_style=COLOR_SUMMARY,
        )
    if artifacts:
        text.append("  Artifacts:\n", style=COLOR_SUMMARY)
        append_agent_artifact_paths(
            text,
            artifact_paths=artifacts,
            hint_state=hint_state,
            indent="    ",
        )
