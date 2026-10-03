"""Public import facade for memory panel history tests.

The cases live in private modules so they stay out of pytest's direct file discovery;
this module keeps the original import path and collection behavior.
"""

from __future__ import annotations

from rich.console import Console

from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps
from sase.ace.tui.keymaps.bindings import build_memory_bindings, memory_help_bindings
from sase.ace.tui.modals.memory_panel_history import (
    fetch_history_summary,
    history_cache_key,
    selector_for_node,
)
from sase.ace.tui.modals.memory_panel_rendering import (
    build_note_card_meta,
    build_panel_footer,
)
from tests.ace.tui.modals.memory_panel_test_helpers import (
    memory_note,
    scope_ref,
    scope_snapshot,
)

from tests.ace.tui.modals._memory_panel_history_rendering import (
    test_memory_bindings_include_history_and_changes,
    test_panel_footer_always_shows_history_with_notes,
    test_time_strip_clean_now_shows_pill_and_meaning,
    test_time_strip_untracked_and_no_vcs_use_pager_words,
    test_time_strip_indexing_reserves_rows_and_folds,
    test_note_property_grid_has_no_history_row,
    test_note_card_meta_has_no_history_row,
    test_selector_for_node_covers_notes_and_strands,
    test_stale_chip_marks_only_a_kept_snapshot,
)
from tests.ace.tui.modals._memory_panel_history_loading import (
    test_history_scope_uses_content_root_never_cwd,
    test_history_cache_key_includes_scope_subject_and_tip,
    test_history_summary_fetch_is_fail_open,
    test_history_row_loads_without_blocking,
    test_unavailable_history_load_does_not_respawn_workers,
    test_config_schema_accepts_history_keymaps,
    test_no_call_from_thread_in_async_workers_under_ace_tui,
)
from tests.ace.tui.modals._memory_panel_history_opening import (
    test_open_history_key_opens_pager,
    test_open_changes_key_opens_changes_lens,
    test_open_history_failure_surfaces_error_toast,
    test_open_history_stale_selection_drops_the_open,
    test_open_history_key_opens_web_descriptor_and_strand,
    test_open_history_failure_names_the_reason,
    test_open_history_hidden_hub_drops_the_open,
    test_open_history_failure_uses_honest_state_words,
)

__all__ = (
    "Console",
    "MemoryPanelKeymaps",
    "build_memory_bindings",
    "memory_help_bindings",
    "fetch_history_summary",
    "history_cache_key",
    "selector_for_node",
    "build_note_card_meta",
    "build_panel_footer",
    "memory_note",
    "scope_ref",
    "scope_snapshot",
    "test_memory_bindings_include_history_and_changes",
    "test_panel_footer_always_shows_history_with_notes",
    "test_time_strip_clean_now_shows_pill_and_meaning",
    "test_time_strip_untracked_and_no_vcs_use_pager_words",
    "test_time_strip_indexing_reserves_rows_and_folds",
    "test_note_property_grid_has_no_history_row",
    "test_note_card_meta_has_no_history_row",
    "test_selector_for_node_covers_notes_and_strands",
    "test_stale_chip_marks_only_a_kept_snapshot",
    "test_history_scope_uses_content_root_never_cwd",
    "test_history_cache_key_includes_scope_subject_and_tip",
    "test_history_summary_fetch_is_fail_open",
    "test_history_row_loads_without_blocking",
    "test_unavailable_history_load_does_not_respawn_workers",
    "test_config_schema_accepts_history_keymaps",
    "test_no_call_from_thread_in_async_workers_under_ace_tui",
    "test_open_history_key_opens_pager",
    "test_open_changes_key_opens_changes_lens",
    "test_open_history_failure_surfaces_error_toast",
    "test_open_history_stale_selection_drops_the_open",
    "test_open_history_key_opens_web_descriptor_and_strand",
    "test_open_history_failure_names_the_reason",
    "test_open_history_hidden_hub_drops_the_open",
    "test_open_history_failure_uses_honest_state_words",
)
