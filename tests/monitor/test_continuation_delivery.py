"""Ordinary continuation reservation, concurrent dispatch, and receiver adoption."""

from __future__ import annotations

from .test_continuation_delivery_adoption import (
    test_budget_refusal_marks_adopted_delivery_needs_attention,
    test_illegal_skip_of_dispatching_is_rejected,
    test_invoke_adopts_before_fake_provider,
    test_receiver_adopts_before_provider_invocation,
    test_resume_adoption_decision_preserves_acknowledged_records,
    test_schema_version_used_by_transition_request,
    test_wrong_receiver_cannot_transition_delivery,
)
from .test_continuation_delivery_dispatch import (
    test_concurrent_dispatch_spawns_once,
    test_followup_reserves_identity_before_spawn,
    test_injected_crashes_keep_delivery_key_stable,
)
from .test_continuation_delivery_prefix import (
    test_followup_prompt_carries_no_auto_prefix,
    test_epic_launch_monitor_override_is_not_inherited_by_successors,
    test_epic_launch_monitor_override_without_starter_weight_is_not_inherited,
    test_launch_wire_extra_keeps_user_authored_zero,
    test_launch_wire_extra_preserves_canonical_capacity,
    test_queue_launch_prefix_keeps_legacy_zero_when_budget_off,
    test_queue_launch_prefix_keeps_user_authored_zero,
    test_queue_launch_prefix_legacy_zero_does_not_reenter_on_parser,
    test_queue_launch_prefix_omits_implicit_zero,
    test_queue_launch_prefix_omits_legacy_zero_when_budget_on,
    test_queue_launch_prefix_positive_budget_is_parseable,
    test_queue_launch_prefix_prefers_canonical_capacity,
    test_queue_launch_prefix_reauthors_capacity_multiplier,
)

__all__ = [
    "test_followup_prompt_carries_no_auto_prefix",
    "test_budget_refusal_marks_adopted_delivery_needs_attention",
    "test_concurrent_dispatch_spawns_once",
    "test_epic_launch_monitor_override_is_not_inherited_by_successors",
    "test_epic_launch_monitor_override_without_starter_weight_is_not_inherited",
    "test_followup_reserves_identity_before_spawn",
    "test_illegal_skip_of_dispatching_is_rejected",
    "test_injected_crashes_keep_delivery_key_stable",
    "test_invoke_adopts_before_fake_provider",
    "test_launch_wire_extra_keeps_user_authored_zero",
    "test_launch_wire_extra_preserves_canonical_capacity",
    "test_queue_launch_prefix_keeps_legacy_zero_when_budget_off",
    "test_queue_launch_prefix_keeps_user_authored_zero",
    "test_queue_launch_prefix_legacy_zero_does_not_reenter_on_parser",
    "test_queue_launch_prefix_omits_implicit_zero",
    "test_queue_launch_prefix_omits_legacy_zero_when_budget_on",
    "test_queue_launch_prefix_positive_budget_is_parseable",
    "test_queue_launch_prefix_prefers_canonical_capacity",
    "test_queue_launch_prefix_reauthors_capacity_multiplier",
    "test_receiver_adopts_before_provider_invocation",
    "test_resume_adoption_decision_preserves_acknowledged_records",
    "test_schema_version_used_by_transition_request",
    "test_wrong_receiver_cannot_transition_delivery",
]
