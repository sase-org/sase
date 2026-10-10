"""Persisted protocol guards for monitor continuation records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MONITOR_CONTINUATION_PROTOCOL_FIELD = "monitor_continuation_protocol"
MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1 = "records_v1"
MONITOR_CONTINUATION_PROTOCOL_LEGACY = "legacy"

_RECORDS_V1_SENTINEL_FIELDS = frozenset(
    {
        "continuation_intent_id",
        "continuation_intent_ref",
        "continuation_intent_manifest_ref",
        "continuation_monitor_result_id",
        "continuation_monitor_result_ref",
        "continuation_monitor_result_path",
        "continuation_monitor_result_node_ref",
        "continuation_monitor_result_manifest_ref",
        "continuation_outcome_policy_ref",
        "continuation_parent_node_ids",
        "monitor_completion_ref",
        "monitor_policy_digest",
        "monitor_profile",
    }
)


def monitor_continuation_protocol_for_new_start() -> str:
    """Return the protocol a newly admitted monitor run should persist.

    New starts unconditionally use versioned continuation records. The
    persisted protocol on each existing monitor still governs its own
    settlement and recovery (see
    :func:`monitor_continuation_records_enabled_for_meta`).
    """

    return MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1


def monitor_continuation_records_enabled_for_meta(meta: Mapping[str, Any]) -> bool:
    """Return whether an existing monitor must keep versioned semantics.

    Every new start persists the versioned protocol, but once a monitor
    member exists its persisted protocol decides settlement,
    reconciliation, resume, and follow-up delivery. Pre-protocol records
    are treated as v1 only when they already carry v1 continuation
    fields; otherwise they remain legacy.
    """

    protocol = meta.get(MONITOR_CONTINUATION_PROTOCOL_FIELD)
    if protocol == MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1:
        return True
    if protocol == MONITOR_CONTINUATION_PROTOCOL_LEGACY:
        return False
    if protocol is not None:
        return True
    return _has_records_v1_sentinel(meta)


def _has_records_v1_sentinel(meta: Mapping[str, Any]) -> bool:
    for key in _RECORDS_V1_SENTINEL_FIELDS:
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(
            isinstance(item, str) and item.strip() for item in value
        ):
            return True
    return False


__all__ = [
    "MONITOR_CONTINUATION_PROTOCOL_FIELD",
    "MONITOR_CONTINUATION_PROTOCOL_LEGACY",
    "MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1",
    "monitor_continuation_protocol_for_new_start",
    "monitor_continuation_records_enabled_for_meta",
]
