"""Regression tests for ACE restart waiting after code-changing updates.

The public test module stays stable while its cases live in focused private modules.
"""

from __future__ import annotations

from sase.ace.tui._proc_observer_models import is_install_mutation_row
from sase.ace.tui.actions._proc_action_completion import ProcCompletionActionsMixin
from sase.ace.tui.actions._proc_action_types import ProcCallbackConfig
from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcCompletionRecord,
    ProcObserverSnapshot,
    ProcProjection,
    recount_projection,
    store_proc_row,
)
from sase.ace.tui.update_restart import (
    RestartBlocker,
    collect_restart_blockers,
    restart_after_update_when_ready,
    running_background_procs,
)
from sase.monitor_state import MONITOR_PROC_ORIGIN
from sase.ops import DurableOperationResult
from sase.procs import Proc, TUI_PROC_KIND
from sase.procs.service_meta import (
    SERVICE_HOST_ORIGIN,
    SERVICE_ONESHOT_ORIGIN,
    SERVICE_PROC_MODE_DAEMON,
    SERVICE_PROC_MODE_ONESHOT,
    SERVICE_PROC_SOURCE_BUILTIN,
    SERVICE_PROC_SOURCE_TRANSIENT,
    ProcServiceBlock,
)

from ._update_restart_blockers import (
    test_tool_run_rows_do_not_block_restart,
    test_renamed_tool_run_argv_still_does_not_block,
    test_ordinary_durable_work_does_not_block_restart,
    test_visibility_cannot_control_restart_safety,
    test_daemon_only_projection_restarts_immediately,
    test_session_overlay_blocks_even_after_worker_status_settles,
    test_leftover_session_worker_key_blocks_without_overlay,
    test_finished_submit_worker_still_blocks_until_map_pops,
    test_submission_placeholder_and_durable_install_dedup,
    test_install_mutations_block_regardless_of_session,
    test_plugin_install_is_not_an_update_lane_row,
    test_monitor_and_daemon_are_not_install_mutations,
    test_local_legacy_tui_blocks_and_other_tui_does_not,
    test_mixed_independent_work_waits_only_for_local_worker,
    test_mixed_kind_wait_copy_joins_groups,
)

from ._update_restart_queue import (
    test_coalesced_request_with_zero_blockers_restarts_immediately,
    test_stale_timer_does_not_restart_twice,
    test_timeout_summary_uses_actual_blockers,
    test_tracked_deferred_publishes_pending_and_refreshes_on_poll,
    test_immediate_restart_publishes_nothing,
    test_untracked_chain_never_publishes,
    test_second_tracked_request_coalesces_into_one_chain,
    test_pending_cleared_when_restart_missing,
)

from ._update_restart_callbacks import (
    test_callback_bearing_durable_row_blocks_restart,
    test_handoff_placeholder_and_durable_callback_dedup,
    test_submit_worker_and_callback_under_placeholder_dedup,
    test_unobserved_watched_proc_blocks_and_stale_keys_do_not,
    test_install_row_with_callback_is_reported_as_install,
    test_independent_rows_never_block_even_with_session_id,
    test_mixed_work_waits_only_for_callback_sync_then_delivers,
    test_restart_from_own_callback_does_not_wait_on_itself,
    test_callback_timeout_warning_names_the_proc,
)

__all__ = [
    "is_install_mutation_row",
    "ProcCompletionActionsMixin",
    "ProcCallbackConfig",
    "ObservedProc",
    "ProcCompletionRecord",
    "ProcObserverSnapshot",
    "ProcProjection",
    "recount_projection",
    "store_proc_row",
    "RestartBlocker",
    "collect_restart_blockers",
    "restart_after_update_when_ready",
    "running_background_procs",
    "MONITOR_PROC_ORIGIN",
    "DurableOperationResult",
    "Proc",
    "TUI_PROC_KIND",
    "SERVICE_HOST_ORIGIN",
    "SERVICE_ONESHOT_ORIGIN",
    "SERVICE_PROC_MODE_DAEMON",
    "SERVICE_PROC_MODE_ONESHOT",
    "SERVICE_PROC_SOURCE_BUILTIN",
    "SERVICE_PROC_SOURCE_TRANSIENT",
    "ProcServiceBlock",
    "test_tool_run_rows_do_not_block_restart",
    "test_renamed_tool_run_argv_still_does_not_block",
    "test_ordinary_durable_work_does_not_block_restart",
    "test_visibility_cannot_control_restart_safety",
    "test_daemon_only_projection_restarts_immediately",
    "test_session_overlay_blocks_even_after_worker_status_settles",
    "test_leftover_session_worker_key_blocks_without_overlay",
    "test_finished_submit_worker_still_blocks_until_map_pops",
    "test_submission_placeholder_and_durable_install_dedup",
    "test_install_mutations_block_regardless_of_session",
    "test_plugin_install_is_not_an_update_lane_row",
    "test_monitor_and_daemon_are_not_install_mutations",
    "test_local_legacy_tui_blocks_and_other_tui_does_not",
    "test_mixed_independent_work_waits_only_for_local_worker",
    "test_mixed_kind_wait_copy_joins_groups",
    "test_coalesced_request_with_zero_blockers_restarts_immediately",
    "test_stale_timer_does_not_restart_twice",
    "test_timeout_summary_uses_actual_blockers",
    "test_tracked_deferred_publishes_pending_and_refreshes_on_poll",
    "test_immediate_restart_publishes_nothing",
    "test_untracked_chain_never_publishes",
    "test_second_tracked_request_coalesces_into_one_chain",
    "test_pending_cleared_when_restart_missing",
    "test_callback_bearing_durable_row_blocks_restart",
    "test_handoff_placeholder_and_durable_callback_dedup",
    "test_submit_worker_and_callback_under_placeholder_dedup",
    "test_unobserved_watched_proc_blocks_and_stale_keys_do_not",
    "test_install_row_with_callback_is_reported_as_install",
    "test_independent_rows_never_block_even_with_session_id",
    "test_mixed_work_waits_only_for_callback_sync_then_delivers",
    "test_restart_from_own_callback_does_not_wait_on_itself",
    "test_callback_timeout_warning_names_the_proc",
]
