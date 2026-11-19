"""Helpers for on-demand hydration of projected artifact-index records."""

from __future__ import annotations

from ._projected_record_detail import (
    mark_projected_agent_hydration_attempted,
    mark_projected_agent_hydration_pending,
    prepare_projected_agent_copy,
    projected_agent_compact_copy_value,
    projected_agent_needs_hydration,
    projected_agent_waiting_for_hydration,
)
from ._projected_record_load import (
    hydrate_projected_agent,
    load_projected_agent_record,
    resolve_linked_repos,
    resolve_step_output,
)
from ._projected_record_restore import apply_projected_agent_record

__all__ = [
    "apply_projected_agent_record",
    "hydrate_projected_agent",
    "load_projected_agent_record",
    "mark_projected_agent_hydration_attempted",
    "mark_projected_agent_hydration_pending",
    "prepare_projected_agent_copy",
    "projected_agent_compact_copy_value",
    "projected_agent_needs_hydration",
    "projected_agent_waiting_for_hydration",
    "resolve_linked_repos",
    "resolve_step_output",
]
