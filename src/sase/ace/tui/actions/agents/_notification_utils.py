"""Compatibility facade for split notification helpers.

The implementation now lives in focused sibling modules; this module
re-exports the previous public surface so existing import sites keep working:

- :mod:`._notification_agent_targeting` — roster and row targeting.
- :mod:`._notification_matching` — suffixes, predicates, keys, and matching.
- :mod:`._notification_delta_dirs` — exact completion/pending-gate dir resolution.
- :mod:`._notification_gate_refresh` — refresh orchestration and gate receipts.

Two historical private names remain importable here for test call sites
(``test_gate_failure_recovery`` and
``test_agent_settlement_notification_match``); new code should use the
public spellings.
"""

from __future__ import annotations

from ._notification_agent_targeting import (
    TabName,
    agent_artifact_dir,
    call_schedule_agents_refresh,
    callable_accepts_kwarg,
    loaded_real_agent_roster,
    refresh_notification_agent_from_cache,
    resolve_notification_agent,
)
from ._notification_delta_dirs import (
    add_loaded_family_chain_artifact_dirs,
    completion_notification_delta_dirs,
    pending_gate_notification_delta_dirs,
    prepare_pending_gate_notification_refresh,
)
from ._notification_gate_refresh import (
    accepted_gate_shell_artifact_dir,
    apply_disappeared_plan_notification_refresh,
    gate_decision_exact_artifact_dirs,
    gate_decision_is_visible,
    prepare_disappeared_plan_notification_refresh,
    refresh_notification_agent_or_request,
    request_gate_decision_refresh,
    request_notification_agents_refresh,
    schedule_gate_decision_receipt_refresh,
)
from ._notification_matching import (
    FAMILY_ROOT_SUFFIX_KEYS,
    PENDING_GATE_REFRESH_ACTIONS,
    SETTLEMENT_NOTIFICATION_SENDERS,
    active_completion_agent_keys,
    active_row_owned_notification_keys,
    agent_completion_notification_matches_agent,
    agent_row_notification_matches_agent,
    agent_settlement_notification_matches_agent,
    is_active_agent_completion_notification,
    is_active_agent_refresh_notification,
    is_active_agent_settlement_notification,
    is_active_pending_gate_refresh_notification,
    normalized_suffix,
    notification_family_root_suffix,
    notification_raw_suffix,
    pending_gate_notification_suffixes,
    unread_notification_buckets,
)


_request_gate_decision_refresh = request_gate_decision_refresh
_agent_settlement_notification_matches_agent = (
    agent_settlement_notification_matches_agent
)


__all__ = [
    "FAMILY_ROOT_SUFFIX_KEYS",
    "PENDING_GATE_REFRESH_ACTIONS",
    "SETTLEMENT_NOTIFICATION_SENDERS",
    "TabName",
    "_agent_settlement_notification_matches_agent",
    "_request_gate_decision_refresh",
    "accepted_gate_shell_artifact_dir",
    "active_completion_agent_keys",
    "active_row_owned_notification_keys",
    "add_loaded_family_chain_artifact_dirs",
    "agent_artifact_dir",
    "agent_completion_notification_matches_agent",
    "agent_row_notification_matches_agent",
    "agent_settlement_notification_matches_agent",
    "apply_disappeared_plan_notification_refresh",
    "call_schedule_agents_refresh",
    "callable_accepts_kwarg",
    "completion_notification_delta_dirs",
    "gate_decision_exact_artifact_dirs",
    "gate_decision_is_visible",
    "is_active_agent_completion_notification",
    "is_active_agent_refresh_notification",
    "is_active_agent_settlement_notification",
    "is_active_pending_gate_refresh_notification",
    "loaded_real_agent_roster",
    "normalized_suffix",
    "notification_family_root_suffix",
    "notification_raw_suffix",
    "pending_gate_notification_delta_dirs",
    "pending_gate_notification_suffixes",
    "prepare_disappeared_plan_notification_refresh",
    "prepare_pending_gate_notification_refresh",
    "refresh_notification_agent_from_cache",
    "refresh_notification_agent_or_request",
    "request_gate_decision_refresh",
    "request_notification_agents_refresh",
    "resolve_notification_agent",
    "schedule_gate_decision_receipt_refresh",
    "unread_notification_buckets",
]
