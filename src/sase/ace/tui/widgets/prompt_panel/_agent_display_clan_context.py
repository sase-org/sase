"""Exact hint targets for structured clan SASE CONTEXT entries."""

from __future__ import annotations

import os
from collections.abc import Mapping

from sase.ace.patch.models import DeltaEntry
from sase.ace.tui.glossary_reads import GlossaryReadDisplayEvent
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent

from ...models._agent_clan_sections import ClanContextEntry
from ...models.agent_associated_plan import AssociatedPlanSummary, BeadSummary
from ..file_panel._linked_deltas import LinkedDeltaGroup
from ._artifact_files import ArtifactFilePath


def clan_context_entry_hint_target(
    lane_label: str,
    entry: ClanContextEntry,
    *,
    member_workspaces: Mapping[str, str | None],
    fallback_workspace: str | None,
) -> str | None:
    """Return the first addressable path represented by a context row."""
    if lane_label in {"SKILLS", "WORKSPACES"}:
        return None

    member_workspace = next(
        (
            member_workspaces[label]
            for label in entry.member_labels
            if member_workspaces.get(label) is not None
        ),
        fallback_workspace,
    )
    for value in entry.values:
        target = _typed_context_value_path(
            lane_label,
            value,
            member_workspace=member_workspace,
        )
        if target is not None:
            return target
    return None


def _typed_context_value_path(
    lane_label: str,
    value: object,
    *,
    member_workspace: str | None,
) -> str | None:
    if lane_label == "PLAN":
        if isinstance(value, AssociatedPlanSummary):
            return value.actual_path
        if isinstance(value, str):
            return _resolve_path(value, member_workspace)
        return None

    if lane_label == "BEAD":
        if isinstance(value, BeadSummary):
            return value.actual_plan_path
        return None

    if lane_label == "ARTIFACTS":
        if isinstance(value, ArtifactFilePath):
            return value.actual_path
        if isinstance(value, DeltaEntry):
            return _resolve_path(value.path, member_workspace)
        if isinstance(value, LinkedDeltaGroup) and value.entries:
            return _resolve_path(value.entries[0].path, value.workspace_dir)
        if isinstance(value, str):
            return _resolve_path(value, member_workspace)
        return None

    if lane_label == "MEMORY" and isinstance(value, MemoryReadDisplayEvent):
        return value.event.resolved_path
    if lane_label == "GLOSSARY" and isinstance(value, GlossaryReadDisplayEvent):
        return value.event.source_path
    return None


def _resolve_path(path: str, workspace_dir: str | None) -> str:
    """Resolve a delta/path seed with the same semantics as the sase agent."""
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return expanded
    if workspace_dir:
        return os.path.join(workspace_dir, expanded)
    return os.path.abspath(expanded)


__all__ = ["clan_context_entry_hint_target"]
