"""Compatibility facade for the ACE testing DSL tests."""

import asyncio
from collections.abc import Callable
from pathlib import Path
import threading
from unittest.mock import patch

import pytest
from textual.css.stylesheet import Stylesheet

import sase.ace.patch as patch_module
import sase.ace.testing as testing_module
from sase.ace.testing import (
    ACE_PAGE_GROUP_ISOLATION_ENV,
    AcePage,
    AcePageGroup,
    PromptPage,
    clear_fast_stylesheet_cache,
    fast_stylesheet_cache_stats,
    make_changespec as make_patch,  # legacy compatibility alias
)
from sase.ace.tui import AceApp
from sase.ace.tui.actions import artifacts as artifacts_actions
from sase.ace.tui.proc_observer import PROC_OBSERVER_THREAD_NAME


from tests._ace_testing_page import (
    test_ace_page_initial_state,
    test_ace_page_press,
    test_ace_page_screen,
    test_ace_page_export_svg,
    test_ace_page_custom_patches,
    test_expect_state_passes,
    test_expect_state_fails_on_timeout,
    test_expect_state_timeout_preserves_last_value_message,
    test_expect_state_nested_key,
    test_expect_modal,
    test_expect_no_modal,
    test_expect_screen_contains,
    test_expect_screen_contains_timeout,
    test_expect_screen_not_contains,
    test_wait_for,
    test_wait_for_custom_timeout_message,
    test_ace_page_fast_startup_is_structurally_quiet,
)

from tests._ace_testing_startup import (
    test_drain_pump_free_tasks_discards_already_done_tasks,
    test_ace_page_teardown_cancels_textual_workers,
    test_ace_page_real_startup_policy_invokes_production_boundaries,
    test_ace_page_restores_fast_startup_overrides_after_success,
    test_ace_page_preserves_caller_supplied_startup_fixtures,
    test_ace_page_fast_stylesheet_cache_skips_second_parse,
    test_ace_page_fast_stylesheet_cache_invalidates_changed_css_path,
    test_ace_page_fast_stylesheet_cache_still_applies_rules,
    test_ace_page_fast_stylesheet_cache_hydrates_mutable_data_per_app,
)

from tests._ace_testing_group import (
    test_ace_page_group_reuses_page_and_resets_prompt_without_history,
    test_ace_page_group_rejects_overlapping_checkouts,
    test_ace_page_group_reports_reset_hook_leaks,
    test_ace_page_group_clears_disabled_notifications_between_checkouts,
    test_ace_page_group_isolation_mode_creates_distinct_apps,
    test_ace_page_restores_overrides_when_entry_fails,
    test_ace_page_rejects_unknown_startup_policy,
)

from tests._ace_testing_prompt import (
    test_prompt_page_initial_state,
    test_prompt_page_press,
    test_prompt_page_insert_mode,
    test_prompt_page_ta_access,
    test_prompt_page_cursor_setter,
)

__all__ = [
    "asyncio",
    "Callable",
    "Path",
    "threading",
    "patch",
    "pytest",
    "Stylesheet",
    "patch_module",
    "testing_module",
    "ACE_PAGE_GROUP_ISOLATION_ENV",
    "AcePage",
    "AcePageGroup",
    "PromptPage",
    "clear_fast_stylesheet_cache",
    "fast_stylesheet_cache_stats",
    "make_patch",
    "AceApp",
    "artifacts_actions",
    "PROC_OBSERVER_THREAD_NAME",
    "test_ace_page_initial_state",
    "test_ace_page_press",
    "test_ace_page_screen",
    "test_ace_page_export_svg",
    "test_ace_page_custom_patches",
    "test_expect_state_passes",
    "test_expect_state_fails_on_timeout",
    "test_expect_state_timeout_preserves_last_value_message",
    "test_expect_state_nested_key",
    "test_expect_modal",
    "test_expect_no_modal",
    "test_expect_screen_contains",
    "test_expect_screen_contains_timeout",
    "test_expect_screen_not_contains",
    "test_wait_for",
    "test_wait_for_custom_timeout_message",
    "test_ace_page_fast_startup_is_structurally_quiet",
    "test_drain_pump_free_tasks_discards_already_done_tasks",
    "test_ace_page_teardown_cancels_textual_workers",
    "test_ace_page_real_startup_policy_invokes_production_boundaries",
    "test_ace_page_restores_fast_startup_overrides_after_success",
    "test_ace_page_preserves_caller_supplied_startup_fixtures",
    "test_ace_page_fast_stylesheet_cache_skips_second_parse",
    "test_ace_page_fast_stylesheet_cache_invalidates_changed_css_path",
    "test_ace_page_fast_stylesheet_cache_still_applies_rules",
    "test_ace_page_fast_stylesheet_cache_hydrates_mutable_data_per_app",
    "test_ace_page_group_reuses_page_and_resets_prompt_without_history",
    "test_ace_page_group_rejects_overlapping_checkouts",
    "test_ace_page_group_reports_reset_hook_leaks",
    "test_ace_page_group_clears_disabled_notifications_between_checkouts",
    "test_ace_page_group_isolation_mode_creates_distinct_apps",
    "test_ace_page_restores_overrides_when_entry_fails",
    "test_ace_page_rejects_unknown_startup_policy",
    "test_prompt_page_initial_state",
    "test_prompt_page_press",
    "test_prompt_page_insert_mode",
    "test_prompt_page_ta_access",
    "test_prompt_page_cursor_setter",
]
