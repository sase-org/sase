"""Live-tail coverage (epic sase-1b2, bead sase-1b2.18, ``final-live``).

Split facade: the tests now live in ``test_final_live_tail``,
``test_final_live_cards``, and ``test_final_live_loader`` (shared
helpers in ``_final_live_shared``). This module re-exports the public
names so the original import path keeps working. It collects no tests
itself.
"""

from __future__ import annotations

from tests.ace.tui.widgets.decks.final._final_live_shared import NOW
from tests.ace.tui.widgets.decks.final.test_final_live_cards import (
    test_card_hides_tail_before_gate_opens,
    test_card_hides_tail_for_settled_ops,
    test_card_renders_gated_live_tail_for_active_op,
    test_card_tail_caps_at_twelve_lines,
    test_card_tail_never_bleeds_across_agents,
    test_card_tails_follow_newest_run_only,
    test_document_build_threads_live_tail,
)
from tests.ace.tui.widgets.decks.final.test_final_live_loader import (
    test_loader_fresh_bypass_rebuilds_for_tick,
    test_slow_retrying_finalizer_projects_active_tail_end_to_end,
    test_store_final_result_bounds_cache,
)
from tests.ace.tui.widgets.decks.final.test_final_live_tail import (
    test_finalization_active_phases,
    test_follow_pause_and_resume,
    test_follow_target_is_newest_run_with_live_content,
    test_follow_target_names_latest_attempt,
    test_follow_target_skips_runs_without_live_content,
    test_format_live_elapsed,
    test_is_operation_active_treats_missing_exit_as_running,
    test_live_lines_require_active_op_and_open_gate,
    test_live_lines_scoped_to_follow_target,
    test_sanitize_caps_at_twelve_lines,
    test_sanitize_collapses_carriage_returns,
    test_should_live_tick_scope,
    test_tail_gate_delay_zero_renders_immediately,
    test_tail_gate_holds_fast_ops,
    test_tail_gate_unknown_start_stays_closed,
    test_ticker_coalesces_in_flight_and_pause,
)

__test__ = False

__all__ = [
    "NOW",
    "test_card_hides_tail_before_gate_opens",
    "test_card_hides_tail_for_settled_ops",
    "test_card_renders_gated_live_tail_for_active_op",
    "test_card_tail_caps_at_twelve_lines",
    "test_card_tail_never_bleeds_across_agents",
    "test_card_tails_follow_newest_run_only",
    "test_document_build_threads_live_tail",
    "test_finalization_active_phases",
    "test_follow_pause_and_resume",
    "test_follow_target_is_newest_run_with_live_content",
    "test_follow_target_names_latest_attempt",
    "test_follow_target_skips_runs_without_live_content",
    "test_format_live_elapsed",
    "test_is_operation_active_treats_missing_exit_as_running",
    "test_live_lines_require_active_op_and_open_gate",
    "test_live_lines_scoped_to_follow_target",
    "test_loader_fresh_bypass_rebuilds_for_tick",
    "test_sanitize_caps_at_twelve_lines",
    "test_sanitize_collapses_carriage_returns",
    "test_should_live_tick_scope",
    "test_slow_retrying_finalizer_projects_active_tail_end_to_end",
    "test_store_final_result_bounds_cache",
    "test_tail_gate_delay_zero_renders_immediately",
    "test_tail_gate_holds_fast_ops",
    "test_tail_gate_unknown_start_stays_closed",
    "test_ticker_coalesces_in_flight_and_pause",
]
