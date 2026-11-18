"""Typed chop proposal-launch admission coverage.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_axe_chop_proposal_launch_ordinary import (
    test_ordinary_clan_kill_settles_crossing_launch_without_failing_run,
    test_ordinary_first_run_owns_batch_through_launch,
)
from tests.test_axe_chop_proposal_launch_typed_admission import (
    test_typed_chop_batch_pause_reopens_frozen_bundle_without_rechecking_skips,
    test_typed_chop_proposal_uses_durable_admission_and_chop_env,
    test_typed_chop_recovers_bundle_written_before_outer_batch,
)
from tests.test_axe_chop_proposal_launch_typed_dispatch import (
    test_runner_all_skipped_typed_admission_succeeds_without_agent,
    test_typed_chop_dispatch_carries_launch_hold_key,
    test_typed_chop_dispatch_fails_closed_without_workspace_metadata,
)

__test__ = False

__all__ = [
    "test_ordinary_clan_kill_settles_crossing_launch_without_failing_run",
    "test_ordinary_first_run_owns_batch_through_launch",
    "test_runner_all_skipped_typed_admission_succeeds_without_agent",
    "test_typed_chop_batch_pause_reopens_frozen_bundle_without_rechecking_skips",
    "test_typed_chop_dispatch_carries_launch_hold_key",
    "test_typed_chop_dispatch_fails_closed_without_workspace_metadata",
    "test_typed_chop_proposal_uses_durable_admission_and_chop_env",
    "test_typed_chop_recovers_bundle_written_before_outer_batch",
]
