"""Ranked ARTIFACTS lane for the prompt panel's SASE CONTEXT section."""

from __future__ import annotations

from rich.text import Text

from sase.ace.patch.models import DeltaEntry
from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent
from sase.ace.tui.bead_touches import BEAD_READ_REF_PREFIX, BeadTouchEntry

from ...models.agent import Agent
from ..file_panel._linked_deltas import LinkedDeltaGroup
from ._agent_artifact_reads import append_agent_artifact_read_rows
from ._agent_bead_touches import (
    ResponsiveBeadTouchesSection,
    append_agent_bead_touch_rows,
)
from ._agent_commits import (
    agent_commit_groups,
    append_agent_commit_groups,
    count_agent_commit_groups,
)
from ._agent_context_common import (
    COLOR_ARTIFACTS_SUBHEADER,
    COLOR_BEAD_CLOSED_GLYPH,
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


def _non_bead_reads(
    artifact_reads: tuple[ArtifactReadDisplayEvent, ...],
) -> tuple[ArtifactReadDisplayEvent, ...]:
    """Return artifact reads excluding ``bead:`` refs.

    ``Beads:`` owns every bead interaction (including audited reads, which
    the merge folds in as ``read`` verbs), so ``Reads:`` renders only
    non-bead consultation.
    """
    return tuple(
        item
        for item in artifact_reads
        if not (item.event.ref or "").strip().startswith(BEAD_READ_REF_PREFIX)
    )


def append_agent_artifacts_lane(
    text: Text,
    *,
    agent: Agent | None = None,
    delta_entries: list[DeltaEntry] | None = None,
    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = (),
    artifact_file_paths: list[ArtifactFilePath] | None = None,
    artifact_reads: tuple[ArtifactReadDisplayEvent, ...] = (),
    bead_touch_entries: tuple[BeadTouchEntry, ...] = (),
    hint_state: HeaderHintState | None = None,
    bead_touches_section: ResponsiveBeadTouchesSection | None = None,
) -> tuple[int, int] | None:
    """Append beads, reads, commits, deltas, and artifact files as one ranked lane.

    When ``bead_touches_section`` is supplied, its logical 80-cell text is
    spliced in and the relative range is returned so the header can reflow
    note previews at the visible Context-card width.
    """
    commit_groups = agent_commit_groups(agent) if agent is not None else ()
    deltas = visible_agent_delta_entries(delta_entries or ())
    linked_groups = visible_agent_linked_delta_groups(linked_delta_groups)
    artifact_files = artifact_file_paths or []
    reads = _non_bead_reads(artifact_reads)

    closed_count = sum(
        1
        for entry in bead_touch_entries
        if entry.agent_close is not None and entry.agent_close.standing
    )
    detail_parts: list[str] = []
    if bead_touch_entries:
        detail_parts.append(count_phrase(len(bead_touch_entries), "bead"))
    if reads:
        detail_parts.append(count_phrase(len(reads), "read"))
    commit_count = count_agent_commit_groups(commit_groups)
    if commit_count:
        detail_parts.append(count_phrase(commit_count, "commit"))
    delta_count = len(deltas) + sum(len(group.entries) for group in linked_groups)
    if delta_count:
        detail_parts.append(count_phrase(delta_count, "file"))
    if artifact_files:
        detail_parts.append(count_phrase(len(artifact_files), "artifact file"))
    if not detail_parts:
        return None

    details = Text()
    details.append(detail_parts[0], style=COLOR_SUMMARY)
    if bead_touch_entries and closed_count:
        details.append(" (", style=COLOR_SUMMARY)
        details.append(f"✓ {closed_count} closed", style=COLOR_BEAD_CLOSED_GLYPH)
        details.append(")", style=COLOR_SUMMARY)
    for part in detail_parts[1:]:
        details.append(" · ", style=COLOR_SUMMARY)
        details.append(part, style=COLOR_SUMMARY)

    append_context_lane_header(
        text,
        "ARTIFACTS",
        label_style=COLOR_ARTIFACTS_SUBHEADER,
        details=details,
    )
    beads_range: tuple[int, int] | None = None
    if bead_touch_entries:
        text.append("  Beads:\n", style=COLOR_SUMMARY)
        if bead_touches_section is not None:
            start = len(text)
            text.append_text(bead_touches_section.logical_text)
            beads_range = (start, len(text))
        else:
            append_agent_bead_touch_rows(
                text,
                entries=bead_touch_entries,
                hint_state=hint_state,
            )
    if reads:
        text.append("  Reads:\n", style=COLOR_SUMMARY)
        append_agent_artifact_read_rows(
            text,
            events=reads,
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
    return beads_range
