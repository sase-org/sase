"""Completion-source tests for the ``:`` Command Line (sase-17x.13.10.4).

Split facade: the tests now live in ``test_completion_sources_cache``,
``test_completion_sources_cd``, ``test_completion_sources_paths``, and
``test_completion_sources_slots`` (shared helpers in
``_completion_sources_shared``). This module re-exports the public names
so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.command_line._completion_sources_shared import (
    grammar_handle,
    history_file,
)
from tests.ace.tui.command_line.test_completion_sources_cache import (
    test_finishing_a_command_drops_the_stale_in_flight_fetch,
    test_finishing_a_command_refetches_past_the_disk_cache,
    test_finishing_a_command_under_an_active_menu_refetches_on_next_render,
    test_invalidate_retires_in_flight_fetches_and_distrusts_the_disk_cache,
)
from tests.ace.tui.command_line.test_completion_sources_cd import (
    test_cd_completes_directories_projects_and_unpin_on_the_screen,
    test_cd_offers_unpin_in_the_empty_menu_after_the_directories,
    test_cd_plus_prefers_the_canonical_key_over_an_equal_label,
    test_cd_plus_resolves_the_labels_completion_offers_and_home,
)
from tests.ace.tui.command_line.test_completion_sources_paths import (
    test_path_rows_reach_the_popup_for_a_cwd_slot_through_complete,
    test_path_scan_lists_dotfiles_only_once_the_typed_name_starts_with_a_dot,
    test_path_scan_runs_in_the_debounced_worker_not_on_the_keystroke,
)
from tests.ace.tui.command_line.test_completion_sources_slots import (
    test_marked_row_for_a_variadic_agent_slot_on_the_mounted_screen,
    test_probe_keeps_a_strong_reference_to_its_append_task,
    test_probe_starts_at_key_receipt_not_at_the_refresh,
    test_proc_slot_fetches_from_the_provider_when_app_state_is_empty,
    test_project_slot_merges_provider_rows_behind_the_tui_projects,
    test_project_slots_always_fetch_but_proc_and_agent_slots_only_when_empty,
    test_provider_rows_merge_behind_in_memory_rows_without_duplicates,
)

__test__ = False

__all__ = [
    "grammar_handle",
    "history_file",
    "test_cd_completes_directories_projects_and_unpin_on_the_screen",
    "test_cd_offers_unpin_in_the_empty_menu_after_the_directories",
    "test_cd_plus_prefers_the_canonical_key_over_an_equal_label",
    "test_cd_plus_resolves_the_labels_completion_offers_and_home",
    "test_finishing_a_command_drops_the_stale_in_flight_fetch",
    "test_finishing_a_command_refetches_past_the_disk_cache",
    "test_finishing_a_command_under_an_active_menu_refetches_on_next_render",
    "test_invalidate_retires_in_flight_fetches_and_distrusts_the_disk_cache",
    "test_marked_row_for_a_variadic_agent_slot_on_the_mounted_screen",
    "test_path_rows_reach_the_popup_for_a_cwd_slot_through_complete",
    "test_path_scan_lists_dotfiles_only_once_the_typed_name_starts_with_a_dot",
    "test_path_scan_runs_in_the_debounced_worker_not_on_the_keystroke",
    "test_probe_keeps_a_strong_reference_to_its_append_task",
    "test_probe_starts_at_key_receipt_not_at_the_refresh",
    "test_proc_slot_fetches_from_the_provider_when_app_state_is_empty",
    "test_project_slot_merges_provider_rows_behind_the_tui_projects",
    "test_project_slots_always_fetch_but_proc_and_agent_slots_only_when_empty",
    "test_provider_rows_merge_behind_in_memory_rows_without_duplicates",
]
