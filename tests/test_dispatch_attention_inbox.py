"""Compatibility facade for remote attention inbox tests.

The concrete tests live in focused modules. Keep their original import path
available without collecting the re-exported tests a second time.
"""

from __future__ import annotations

from tests._dispatch_attention_inbox_helpers import (
    inbox_notification_store_file as notification_store_file,
)
from tests.test_dispatch_attention_inbox_legacy import (
    test_legacy_auto_dismissal_does_not_carry_to_the_stable_row,
    test_legacy_dismissal_of_an_older_revision_does_not_hide_a_new_one,
    test_legacy_undismissed_row_folds_into_the_stable_row,
    test_legacy_user_dismissal_carries_to_the_stable_row,
)
from tests.test_dispatch_attention_inbox_lifecycle import (
    test_attention_inventory_cached_repeat_never_resurfaces_user_dismissal,
    test_attention_inventory_creates_durable_remote_attention_notification,
    test_attention_inventory_dismissal_sticks_for_its_revision,
    test_attention_inventory_keeps_user_dismissed_pending_request,
    test_attention_inventory_new_revision_keeps_one_row_per_request,
    test_attention_inventory_new_revision_resurfaces_user_dismissed_row,
    test_attention_inventory_resurfaces_own_auto_dismissal,
    test_attention_inventory_same_revision_re_emission_writes_nothing,
)
from tests.test_dispatch_attention_inbox_reconcile import (
    test_attention_inventory_absence_from_fresh_host_dismisses_stale_request,
    test_attention_inventory_incomplete_page_does_not_settle_absences,
    test_attention_inventory_new_revision_supersedes_old_decision,
    test_attention_inventory_unavailable_host_does_not_settle_absences,
    test_consecutive_polls_differing_only_in_observed_at_skip_rewrite,
    test_fetch_attention_inventory_skips_facade_without_configured_machines,
    test_reconcile_atomic_write_preserves_concurrent_remote_row_dismissal,
    test_reconcile_delta_write_preserves_concurrent_completion_dismissal,
    test_remote_attention_payload_is_string_encoded,
)

__test__ = False

__all__ = [
    "notification_store_file",
    "test_attention_inventory_absence_from_fresh_host_dismisses_stale_request",
    "test_attention_inventory_cached_repeat_never_resurfaces_user_dismissal",
    "test_attention_inventory_creates_durable_remote_attention_notification",
    "test_attention_inventory_dismissal_sticks_for_its_revision",
    "test_attention_inventory_incomplete_page_does_not_settle_absences",
    "test_attention_inventory_keeps_user_dismissed_pending_request",
    "test_attention_inventory_new_revision_keeps_one_row_per_request",
    "test_attention_inventory_new_revision_resurfaces_user_dismissed_row",
    "test_attention_inventory_new_revision_supersedes_old_decision",
    "test_attention_inventory_resurfaces_own_auto_dismissal",
    "test_attention_inventory_same_revision_re_emission_writes_nothing",
    "test_attention_inventory_unavailable_host_does_not_settle_absences",
    "test_consecutive_polls_differing_only_in_observed_at_skip_rewrite",
    "test_fetch_attention_inventory_skips_facade_without_configured_machines",
    "test_legacy_auto_dismissal_does_not_carry_to_the_stable_row",
    "test_legacy_dismissal_of_an_older_revision_does_not_hide_a_new_one",
    "test_legacy_undismissed_row_folds_into_the_stable_row",
    "test_legacy_user_dismissal_carries_to_the_stable_row",
    "test_reconcile_atomic_write_preserves_concurrent_remote_row_dismissal",
    "test_reconcile_delta_write_preserves_concurrent_completion_dismissal",
    "test_remote_attention_payload_is_string_encoded",
]
