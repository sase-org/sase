"""Result-contract coverage for gate-shell reclaim sweeps (facade).

The tests formerly defined here now live in
`test_reclaim_errors.py` (summary error capture/cap and dict contract),
`test_reclaim_dispositions.py` (single-gate bundle-expiry and bundle-less
dispositions), and `test_reclaim_reconcile.py` (handoff reconcile). This
module lazily re-exports every public test so the historic import path keeps
working.

Re-exports resolve through PEP 562 `__getattr__` with no `__dir__` entries,
so pytest collects each test exactly once from its owning module instead of
twice through this facade. Only public test names are re-exported; no
`_`-prefixed name is imported across the split modules.
"""

from __future__ import annotations

# ruff: noqa: F822 -- __all__ entries resolve lazily via __getattr__ below and
# are intentionally not bound statically, so pytest collects each test only
# from its owning module.

import importlib

from tests.gate_turn._cli_fixtures import gate_turn_home

__all__ = [
    "gate_turn_home",
    "test_reclaim_records_error_details_and_continues",
    "test_reclaim_error_details_are_capped",
    "test_reclaim_summary_to_dict_omits_error_details",
    "test_reclaim_defers_an_accepted_unfinished_gate_without_settling",
    "test_reclaim_settles_an_unaccepted_expired_review_gate_as_timeout",
    "test_reclaim_settles_an_unaccepted_expired_grace_gate_as_lost",
    "test_reclaim_expired_review_yields_to_a_racing_acceptance",
    "test_reclaim_expired_grace_yields_to_a_racing_completion",
    "test_reclaim_raises_on_a_receipt_naming_a_different_gate",
    "test_reclaim_defers_a_bundle_less_member_while_its_lane_is_locked",
    "test_reclaim_settles_a_bundle_less_member_lost_once_its_lane_is_free",
    "test_reclaim_defers_an_unreadable_bundle_while_its_lane_is_locked",
    "test_reclaim_spares_a_stale_snapshot_whose_bundle_is_now_reachable",
    "test_reconcile_reads_the_artifact_index_once_for_every_gate",
    "test_reconcile_refreshes_the_snapshot_once_for_a_gate_changed_after_it",
    "test_reconcile_refreshes_the_snapshot_at_most_once_for_two_changed_gates",
    "test_reconcile_defers_a_gate_still_changed_after_its_refresh",
    "test_reconcile_skips_a_refresh_when_it_would_not_fit_before_the_deadline",
    "test_reconcile_defers_everything_when_its_deadline_has_already_passed",
    "test_reclaim_and_reconcile_share_one_caller_provided_snapshot",
    "test_reconcile_saves_its_cursor_after_each_gate",
    "test_reconcile_defers_gates_past_its_time_budget_then_resumes",
]

_LAZY_SUBMODULES = (
    ".test_reclaim_errors",
    ".test_reclaim_dispositions",
    ".test_reclaim_reconcile",
)


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    for submodule in _LAZY_SUBMODULES:
        module = importlib.import_module(submodule, __package__)
        try:
            return getattr(module, name)
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
