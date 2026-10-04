"""Tests for applying prompt-stash restore picker results (facade).

The tests formerly defined here now live in
`test_prompt_stash_restore_confirm_apply.py` (pop / keep / delete confirms,
pin toggle, keep-only confirms) and
`test_prompt_stash_restore_confirm_robustness.py` (cursor propagation,
in-place deletes, restore-capture hardening). This module lazily re-exports
every public test so the historic import path keeps working.

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

__all__ = [
    "test_confirm_restores_into_mounted_bar_in_order",
    "test_confirm_restores_bundle_row_into_mounted_bar",
    "test_confirm_without_bar_mounts_home_with_combined_text",
    "test_confirm_without_bar_mounts_single_body_as_macro_markdown",
    "test_confirm_delete_only_pops_without_loading",
    "test_confirm_restore_and_delete_mixed_summary",
    "test_confirm_none_is_noop",
    "test_bundle_pin_toggled_persists_and_refreshes_badge_counts",
    "test_confirm_keep_only_loads_without_popping",
    "test_confirm_keep_only_single_restore_summary",
    "test_confirm_keep_only_expands_bundle_without_popping",
    "test_confirm_restores_bundle_cursor_on_middle_pane",
    "test_confirm_final_row_cursor_wins_over_earlier_rows",
    "test_confirm_without_bar_passes_final_row_cursor",
    "test_confirm_without_bar_legacy_row_uses_end_fallback",
    "test_delete_requested_removes_one_and_refreshes_badge",
    "test_delete_requested_two_ids_plural_message",
    "test_delete_requested_ignores_other_events",
    "test_confirm_pop_loads_from_pop_outcome_without_snapshot_read",
    "test_confirm_keep_read_failure_does_not_pop",
    "test_confirm_load_failure_rolls_row_back_into_stash",
    "test_confirm_load_and_rollback_failure_toasts_archive_recovery",
    "test_spawned_task_exception_is_logged_and_toasted",
    "test_spawned_task_cancelled_stays_silent",
]

_LAZY_SUBMODULES = (
    ".test_prompt_stash_restore_confirm_apply",
    ".test_prompt_stash_restore_confirm_robustness",
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
