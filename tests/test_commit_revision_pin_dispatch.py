"""Pinned-sibling ordering and end-to-end dispatch pin-follow behavior.

This module is a facade preserving the original import path. The tests
now live in :mod:`tests.test_commit_revision_pin_dispatch_order`,
:mod:`tests.test_commit_revision_pin_dispatch_pin`,
:mod:`tests.test_commit_revision_pin_dispatch_bead`, and
:mod:`tests.test_commit_revision_pin_dispatch_repair`. Only public
names are re-exported here, never ``_``-private helpers.
"""

from __future__ import annotations

# The re-exported tests must not be collected twice: pytest collects
# this module (zero tests) and each home module (the real tests).
__test__ = False

from tests.test_commit_revision_pin_dispatch_bead import (
    test_dispatch_pinned_sibling_without_bead_stays_unflagged,
    test_unpushed_resume_downgrades_pinned_sibling_close,
)
from tests.test_commit_revision_pin_dispatch_order import (
    test_dispatch_keeps_today_order_without_pin,
    test_order_unchanged_when_sibling_deferred,
    test_order_unchanged_without_main_commit,
    test_order_unchanged_without_pin,
    test_pinned_sibling_bead_action_downgrade_matrix,
    test_pinned_sibling_ordered_first,
    test_without_pin_protected_drops_host_pin,
)
from tests.test_commit_revision_pin_dispatch_pin import (
    test_dispatch_commits_pinned_sibling_first_and_follows_pin,
    test_dispatch_pinned_sibling_only_carries_keep_and_skips_pin,
)
from tests.test_commit_revision_pin_dispatch_repair import (
    test_pin_follow_after_repair_handoff_keeps_stale_guard,
    test_pin_follow_after_repair_handoff_skips_deferred_main,
    test_pin_follow_after_repair_handoff_succeeds,
)

__all__ = [
    "test_dispatch_commits_pinned_sibling_first_and_follows_pin",
    "test_dispatch_keeps_today_order_without_pin",
    "test_dispatch_pinned_sibling_only_carries_keep_and_skips_pin",
    "test_dispatch_pinned_sibling_without_bead_stays_unflagged",
    "test_order_unchanged_when_sibling_deferred",
    "test_order_unchanged_without_main_commit",
    "test_order_unchanged_without_pin",
    "test_pin_follow_after_repair_handoff_keeps_stale_guard",
    "test_pin_follow_after_repair_handoff_skips_deferred_main",
    "test_pin_follow_after_repair_handoff_succeeds",
    "test_pinned_sibling_bead_action_downgrade_matrix",
    "test_pinned_sibling_ordered_first",
    "test_unpushed_resume_downgrades_pinned_sibling_close",
    "test_without_pin_protected_drops_host_pin",
]
