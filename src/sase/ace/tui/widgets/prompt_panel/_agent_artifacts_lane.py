"""Ranked ARTIFACTS lane for the prompt panel's SASE CONTEXT section."""

from __future__ import annotations

from rich.text import Text

from sase.ace.patch.models import DeltaEntry
from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent

from ...models.agent import Agent
from ..file_panel._linked_deltas import LinkedDeltaGroup
from ._agent_artifact_reads import append_agent_artifact_read_rows
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
from ._artifact_files import ArtifactFilePath, append_artifact_file_paths


def append_agent_artifacts_lane(
    text: Text,
    *,
    agent: Agent | None = None,
    delta_entries: list[DeltaEntry] | None = None,
    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = (),
    artifact_file_paths: list[ArtifactFilePath] | None = None,
    artifact_reads: tuple[ArtifactReadDisplayEvent, ...] = (),
    hint_state: HeaderHintState | None = None,
) -> None:
    """Append reads, commits, deltas, and artifact files as one ranked lane."""
    commit_groups = agent_commit_groups(agent) if agent is not None else ()
    deltas = visible_agent_delta_entries(delta_entries or ())
    linked_groups = visible_agent_linked_delta_groups(linked_delta_groups)
    artifact_files = artifact_file_paths or []

    details: list[str] = []
    if artifact_reads:
        details.append(count_phrase(len(artifact_reads), "read"))
    commit_count = count_agent_commit_groups(commit_groups)
    if commit_count:
        details.append(count_phrase(commit_count, "commit"))
    delta_count = len(deltas) + sum(len(group.entries) for group in linked_groups)
    if delta_count:
        details.append(count_phrase(delta_count, "file"))
    if artifact_files:
        details.append(count_phrase(len(artifact_files), "artifact file"))
    if not details:
        return

    append_context_lane_header(
        text,
        "ARTIFACTS",
        label_style=COLOR_ARTIFACTS_SUBHEADER,
        details=" · ".join(details),
    )
    if artifact_reads:
        text.append("  Reads:\n", style=COLOR_SUMMARY)
        append_agent_artifact_read_rows(
            text,
            events=artifact_reads,
            hint_state=hint_state,
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
    if artifact_files:
        text.append("  Files:\n", style=COLOR_SUMMARY)
        append_artifact_file_paths(
            text,
            artifact_file_paths=artifact_files,
            hint_state=hint_state,
            indent="    ",
        )
