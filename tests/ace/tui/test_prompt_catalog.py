"""Tests for ACE prompt catalog snapshot helpers."""

from __future__ import annotations

from tests.ace.tui._prompt_catalog_sources import (
    test_prompt_source_token_changes_for_macro_file_create as test_prompt_source_token_changes_for_macro_file_create,
)
from tests.ace.tui._prompt_catalog_sources import (
    test_prompt_source_token_changes_for_project_file as test_prompt_source_token_changes_for_project_file,
)
from tests.ace.tui._prompt_catalog_sources import (
    test_prompt_source_token_changes_for_memory_file_create as test_prompt_source_token_changes_for_memory_file_create,
)
from tests.ace.tui._prompt_catalog_sources import (
    test_prompt_source_watch_paths_include_memory_roots as test_prompt_source_watch_paths_include_memory_roots,
)
from tests.ace.tui._prompt_catalog_sources import (
    test_build_prompt_catalog_snapshot_short_circuits_unchanged_token as test_build_prompt_catalog_snapshot_short_circuits_unchanged_token,
)
from tests.ace.tui._prompt_catalog_sources import (
    test_build_prompt_catalog_snapshot_merges_macro_and_user_snippets as test_build_prompt_catalog_snapshot_merges_macro_and_user_snippets,
)
from tests.ace.tui._prompt_catalog_sources import (
    test_prompt_catalog_preserves_explicit_capitalized_collisions as test_prompt_catalog_preserves_explicit_capitalized_collisions,
)
from tests.ace.tui._prompt_catalog_sources import (
    test_config_dirty_build_invalidates_warm_merged_config as test_config_dirty_build_invalidates_warm_merged_config,
)
from tests.ace.tui._prompt_catalog_sources import (
    test_compose_pending_snippet_saves_preserves_existing_and_resolves_refs as test_compose_pending_snippet_saves_preserves_existing_and_resolves_refs,
)
from tests.ace.tui._prompt_catalog_app import (
    test_app_prompt_catalog_returns_stable_assist_list_until_snapshot_changes as test_app_prompt_catalog_returns_stable_assist_list_until_snapshot_changes,
)
from tests.ace.tui._prompt_catalog_app import (
    test_exact_warm_catalog_does_not_fallback_to_default_project as test_exact_warm_catalog_does_not_fallback_to_default_project,
)
from tests.ace.tui._prompt_catalog_app import (
    test_fresh_snapshot_retires_only_matching_pending_saves as test_fresh_snapshot_retires_only_matching_pending_saves,
)
from tests.ace.tui._prompt_catalog_app import (
    test_older_catalog_generation_cannot_erase_pending_save as test_older_catalog_generation_cannot_erase_pending_save,
)
from tests.ace.tui._prompt_catalog_app import (
    test_catalog_rebuild_coalescing_keeps_queued_config_dirty as test_catalog_rebuild_coalescing_keeps_queued_config_dirty,
)
from tests.ace.tui._prompt_catalog_app import (
    test_catalog_loading_worker_does_not_block_event_loop as test_catalog_loading_worker_does_not_block_event_loop,
)
from tests.ace.tui._prompt_catalog_watchers import (
    test_config_watcher_burst_carries_dirty_signal_to_rebuild as test_config_watcher_burst_carries_dirty_signal_to_rebuild,
)
from tests.ace.tui._prompt_catalog_watchers import (
    test_config_watcher_invalidates_repo_mention_catalogs as test_config_watcher_invalidates_repo_mention_catalogs,
)
from tests.ace.tui._prompt_catalog_watchers import (
    test_warm_prompt_repo_mention_catalog_schedules_once as test_warm_prompt_repo_mention_catalog_schedules_once,
)
from tests.ace.tui._prompt_catalog_watchers import (
    test_prompt_source_watch_growth_is_noop_without_watcher as test_prompt_source_watch_growth_is_noop_without_watcher,
)
from tests.ace.tui._prompt_catalog_watchers import (
    test_prompt_source_watch_growth_installs_and_reconciles_once as test_prompt_source_watch_growth_installs_and_reconciles_once,
)
from tests.ace.tui._prompt_catalog_watchers import (
    test_prompt_source_watch_growth_discards_replaced_watcher as test_prompt_source_watch_growth_discards_replaced_watcher,
)
from tests.ace.tui._prompt_catalog_watchers import (
    test_prompt_source_watch_growth_coalesces_rapid_ensures as test_prompt_source_watch_growth_coalesces_rapid_ensures,
)
from tests.ace.tui._prompt_catalog_watchers import (
    test_catalog_getters_never_stop_start_or_join_watcher as test_catalog_getters_never_stop_start_or_join_watcher,
)
