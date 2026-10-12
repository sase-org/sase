"""Backward-compatible public import path for Archive action tests."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_TEST_MODULES = {
    "test_guard_inactive_in_inbox": "test_agent_archive_actions_guards",
    "test_guard_inactive_in_inbox_without_flag": "test_agent_archive_actions_guards",
    "test_each_live_only_key_family_guarded": "test_agent_archive_actions_guards",
    "test_tab_and_tribe_guard_messages": "test_agent_archive_actions_guards",
    "test_live_guard_names_archived_row": "test_agent_archive_actions_guards",
    "test_guard_never_mutates_parked_inbox_state": "test_agent_archive_actions_guards",
    "test_kill_entry_point_guarded": "test_agent_archive_actions_guards",
    "test_remaining_inbox_actions_are_guarded_or_use_archive_selection": (
        "test_agent_archive_actions_guards"
    ),
    "test_tribe_and_tab_entries_guarded": "test_agent_archive_actions_guards",
    "test_guard_toast_names_configured_toggle_key": "test_agent_archive_actions_guards",
    "test_kill_and_edit_revert_and_quick_launch_are_guarded": (
        "test_agent_archive_actions_guards"
    ),
    "test_toggle_mark_routes_to_archive_marks": "test_agent_archive_actions_marks",
    "test_mark_banner_tail_pulse_rejected": "test_agent_archive_actions_marks",
    "test_archive_marks_independent_from_inbox_marks": (
        "test_agent_archive_actions_marks"
    ),
    "test_archive_marks_parked_with_view_state": "test_agent_archive_actions_marks",
    "test_marked_run_keys_expand_containers": "test_agent_archive_actions_marks",
    "test_marked_run_keys_exclude_inbox_identities": "test_agent_archive_actions_marks",
    "test_archive_footer_bindings_selection": "test_agent_archive_actions_marks",
    "test_archive_footer_bindings_empty_without_selection": (
        "test_agent_archive_actions_marks"
    ),
    "test_archive_footer_bindings_container_and_marks": (
        "test_agent_archive_actions_marks"
    ),
    "test_compute_archive_bindings_restore_without_live_chips": (
        "test_agent_archive_actions_marks"
    ),
    "test_unread_attention_accounting_untouched": "test_agent_archive_actions_marks",
    "test_availability_hides_live_actions_in_archive": (
        "test_agent_archive_actions_availability"
    ),
    "test_command_palette_hides_live_only_actions_in_archive": (
        "test_agent_archive_actions_availability"
    ),
    "test_availability_untouched_in_inbox": "test_agent_archive_actions_availability",
    "test_help_archive_box_content": "test_agent_archive_actions_availability",
    "test_archive_help_and_leader_label_shown_without_flag": (
        "test_agent_archive_actions_availability"
    ),
    "test_toggle_archive_available_from_palette_without_flag": (
        "test_agent_archive_actions_availability"
    ),
    "test_command_palette_hides_every_live_only_action_in_archive": (
        "test_agent_archive_actions_availability"
    ),
    "test_read_target_none_outside_archive": "test_agent_archive_actions_readers",
    "test_read_target_none_for_nav_items": "test_agent_archive_actions_readers",
    "test_copy_context_resolves_without_raise": "test_agent_archive_actions_readers",
    "test_view_files_on_banner_does_not_use_parked_inbox": (
        "test_agent_archive_actions_readers"
    ),
    "test_hydrated_archive_run_is_the_read_target": "test_agent_archive_actions_readers",
    "test_metadata_pager_and_patch_jump_use_hydrated_archive_agent": (
        "test_agent_archive_actions_readers"
    ),
    "test_act_on_agent_routes_to_archive_activate": "test_agent_archive_actions_readers",
}

__all__ = list(_TEST_MODULES)


def __getattr__(name: str) -> Any:
    module_name = _TEST_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f".{module_name}", __package__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
