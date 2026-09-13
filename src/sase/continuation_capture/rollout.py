"""Feature-flag and persisted protocol guards for monitor continuation records."""

from __future__ import annotations

from collections.abc import Mapping
import os
from typing import Any

MONITOR_CONTINUATION_PROTOCOL_FIELD = "monitor_continuation_protocol"
MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1 = "records_v1"
MONITOR_CONTINUATION_PROTOCOL_LEGACY = "legacy"
MONITOR_CONTINUATION_CAPTURE_ENV = "SASE_MONITOR_CONTINUATION"

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


def monitor_continuation_records_enabled() -> bool:
    """Return whether new monitor runs should use versioned continuation records."""

    from sase.feature_flags import FeatureFlag, current_flags

    return current_flags().enabled(FeatureFlag.monitor_continuation_records)


def monitor_continuation_protocol_for_new_start(
    records_enabled: bool | None = None,
) -> str:
    """Return the protocol a newly admitted monitor run should persist."""

    enabled = (
        monitor_continuation_records_enabled()
        if records_enabled is None
        else records_enabled
    )
    return (
        MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1
        if enabled
        else MONITOR_CONTINUATION_PROTOCOL_LEGACY
    )


def monitor_continuation_capture_enabled() -> bool:
    """Return whether this agent process should publish continuation captures."""

    return (
        monitor_continuation_records_enabled()
        or os.environ.get(MONITOR_CONTINUATION_CAPTURE_ENV) == "1"
    )


def monitor_continuation_records_enabled_for_meta(meta: Mapping[str, Any]) -> bool:
    """Return whether an existing monitor must keep versioned semantics.

    The rollout flag chooses only new starts. Once a monitor member exists,
    its persisted protocol decides settlement, reconciliation, resume, and
    follow-up delivery. Pre-protocol records are treated as v1 only when they
    already carry v1 continuation fields; otherwise they remain legacy even
    if the current process has the rollout enabled.
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
    "MONITOR_CONTINUATION_CAPTURE_ENV",
    "MONITOR_CONTINUATION_PROTOCOL_FIELD",
    "MONITOR_CONTINUATION_PROTOCOL_LEGACY",
    "MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1",
    "monitor_continuation_capture_enabled",
    "monitor_continuation_protocol_for_new_start",
    "monitor_continuation_records_enabled",
    "monitor_continuation_records_enabled_for_meta",
]
