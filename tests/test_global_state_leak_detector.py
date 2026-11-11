"""Public test facade for the opt-in global-state leak detector tests."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
import re
import threading
from unittest.mock import patch

import pytest

from tests._global_state_leak_detector import GlobalStateLeakDetector
from tests._global_state_leak_detector_fingerprints import (
    LIVE_CONFIG_TOKEN_REFRESH_THREADS_GLOBAL,
    capture_process_snapshot,
    test_live_config_refresh_thread_is_poisoning_not_warming,
    test_snapshot_includes_live_config_token_refresh_threads,
    test_none_to_pattern_is_warming_but_pattern_change_is_poisoning,
    test_populated_global_reset_to_cold_state_is_cooling,
    test_collection_growth_is_warming_but_existing_value_change_is_poisoning,
    test_cache_like_global_replacement_is_invalidation,
    test_known_snapshot_cache_replacement_is_invalidation,
    test_collection_reset_to_empty_is_cooling,
    test_list_prefix_growth_is_warming_but_rewrite_is_poisoning,
    test_cache_growth_is_warming_but_cache_clear_is_cooling,
    test_live_cache_replacement_is_invalidation,
    test_cache_disappearance_is_invalidation,
    test_environment_delta_names_keys_without_values,
    test_process_snapshot_ignores_harness_git_environment,
    test_process_snapshot_ignores_session_detach_scope_environment,
    test_process_snapshot_uses_isolation_env_ignore_list,
    test_sys_path_append_is_warming_but_rewrite_is_poisoning,
)
from tests._global_state_leak_detector_reporting import (
    test_combined_report_counts_poisoning_and_warming,
    test_combined_report_sorts_by_worker_execution_order,
    test_combined_report_carries_worker_errors,
    test_worker_payload_is_written_to_sidecar,
    test_poisoning_log_lines_name_nodeids_and_change_kinds,
)
from tests._global_state_leak_detector_integration import (
    test_report_only_mode_keeps_pytest_green_on_poison,
    test_fail_on_poison_mode_fails_pytest_on_poison,
    test_drain_after_test_swallows_join_timeout,
    test_protocol_drain_clears_refresh_thread_restarted_after_fixtures,
)

__all__ = [
    "json",
    "lru_cache",
    "Path",
    "re",
    "threading",
    "patch",
    "pytest",
    "GlobalStateLeakDetector",
    "LIVE_CONFIG_TOKEN_REFRESH_THREADS_GLOBAL",
    "capture_process_snapshot",
    "test_live_config_refresh_thread_is_poisoning_not_warming",
    "test_snapshot_includes_live_config_token_refresh_threads",
    "test_none_to_pattern_is_warming_but_pattern_change_is_poisoning",
    "test_populated_global_reset_to_cold_state_is_cooling",
    "test_collection_growth_is_warming_but_existing_value_change_is_poisoning",
    "test_cache_like_global_replacement_is_invalidation",
    "test_known_snapshot_cache_replacement_is_invalidation",
    "test_collection_reset_to_empty_is_cooling",
    "test_list_prefix_growth_is_warming_but_rewrite_is_poisoning",
    "test_cache_growth_is_warming_but_cache_clear_is_cooling",
    "test_live_cache_replacement_is_invalidation",
    "test_cache_disappearance_is_invalidation",
    "test_environment_delta_names_keys_without_values",
    "test_process_snapshot_ignores_harness_git_environment",
    "test_process_snapshot_ignores_session_detach_scope_environment",
    "test_process_snapshot_uses_isolation_env_ignore_list",
    "test_sys_path_append_is_warming_but_rewrite_is_poisoning",
    "test_combined_report_counts_poisoning_and_warming",
    "test_combined_report_sorts_by_worker_execution_order",
    "test_combined_report_carries_worker_errors",
    "test_worker_payload_is_written_to_sidecar",
    "test_report_only_mode_keeps_pytest_green_on_poison",
    "test_fail_on_poison_mode_fails_pytest_on_poison",
    "test_poisoning_log_lines_name_nodeids_and_change_kinds",
    "test_drain_after_test_swallows_join_timeout",
    "test_protocol_drain_clears_refresh_thread_restarted_after_fixtures",
]
