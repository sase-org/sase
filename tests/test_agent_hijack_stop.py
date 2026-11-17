"""Compatibility facade for Agent Hijack stop-protocol tests.

The concrete tests live in focused modules. Keep their original import path
available without collecting the re-exported tests a second time.
"""

from __future__ import annotations

from tests._agent_hijack_stop_support import shared_hijack_home as hijack_home
from tests.test_agent_hijack_stop_cli import (
    test_cli_explain_json_is_additive_and_does_not_stop,
    test_cli_json_envelope,
)
from tests.test_agent_hijack_stop_eligibility import (
    test_claimless_wait_redirects_without_stopping,
    test_completed_agent_is_refused,
    test_old_runner_without_capability_is_refused,
    test_pre_provider_claim_is_held_with_or_without_runner,
    test_re_resolution_refuses_changed_decision_before_pin,
    test_re_resolution_refuses_changed_process_identity_before_pin,
    test_unknown_agent_is_refused,
)
from tests.test_agent_hijack_stop_outcomes import (
    test_fallback_writes_done_json_and_reasserts_pin,
    test_happy_path_reaches_held,
    test_lost_race_keeps_the_real_outcome,
    test_snapshot_failure_still_reaches_held,
    test_survivors_retain_custody_in_stop_blocked,
)
from tests.test_agent_hijack_stop_persist import (
    test_persist_hijack_cancel_uses_latch_backend,
    test_persist_hijack_force_uses_latch_backend,
    test_persist_hijack_latched_stop_is_success,
    test_persist_hijack_uses_the_request_sidecar,
)

__all__ = (
    "hijack_home",
    "test_claimless_wait_redirects_without_stopping",
    "test_cli_explain_json_is_additive_and_does_not_stop",
    "test_cli_json_envelope",
    "test_completed_agent_is_refused",
    "test_fallback_writes_done_json_and_reasserts_pin",
    "test_happy_path_reaches_held",
    "test_lost_race_keeps_the_real_outcome",
    "test_old_runner_without_capability_is_refused",
    "test_persist_hijack_cancel_uses_latch_backend",
    "test_persist_hijack_force_uses_latch_backend",
    "test_persist_hijack_latched_stop_is_success",
    "test_persist_hijack_uses_the_request_sidecar",
    "test_pre_provider_claim_is_held_with_or_without_runner",
    "test_re_resolution_refuses_changed_decision_before_pin",
    "test_re_resolution_refuses_changed_process_identity_before_pin",
    "test_snapshot_failure_still_reaches_held",
    "test_survivors_retain_custody_in_stop_blocked",
    "test_unknown_agent_is_refused",
)

__test__ = False
