"""Immutable artifact-link event publication through document sidecars.

Event canonicalization, local projections, and durable sidecar writes live in
sibling modules so this file stays the public API.
"""

from sase.sdd._artifact_link_event_canonical import (
    ARTIFACT_LINK_EVENT_COMMIT_MESSAGE,
    artifact_link_alias_producer_id,
    artifact_link_derived_producer_id,
    artifact_link_machine_run_id,
    artifact_link_stable_fact_created_at,
    canonical_event,
    edge_put_event_from_row,
    edge_remove_event,
    observation_or_put_event_from_row,
    rows_from_events,
    stable_artifact_link_operation_id,
)
from sase.sdd._artifact_link_event_project import active_operation_ids_for_row
from sase.sdd._artifact_link_event_publish import publish_artifact_link_events

__all__ = [
    "ARTIFACT_LINK_EVENT_COMMIT_MESSAGE",
    "active_operation_ids_for_row",
    "artifact_link_alias_producer_id",
    "artifact_link_derived_producer_id",
    "artifact_link_machine_run_id",
    "artifact_link_stable_fact_created_at",
    "canonical_event",
    "edge_put_event_from_row",
    "edge_remove_event",
    "observation_or_put_event_from_row",
    "publish_artifact_link_events",
    "rows_from_events",
    "stable_artifact_link_operation_id",
]
