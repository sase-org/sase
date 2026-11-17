"""Delayed provider discovery: first paint with fixed panes, then one generation.

Facade preserving the original import path. The suites moved into the
sibling ``_artifacts_post_paint_publication_*`` modules so every file stays at
or under 500 lines; this module re-exports each public test name. Only public
names cross the module boundary here.
"""

from __future__ import annotations

from tests.ace.tui._artifacts_post_paint_publication_bootstrap import (
    test_construction_uses_bootstrap_without_synchronous_discovery,
    test_first_paint_fixed_panes_then_one_coherent_publication,
    test_hidden_agents_startup_publishes_without_losing_selection,
    test_pending_digit_without_target_does_nothing,
    test_pending_provider_jump_applies_only_without_supersede,
    test_render_and_catalog_builders_take_snapshot_without_discovery,
    test_user_navigation_supersedes_pending_provider_jump,
    test_zero_providers_completes_authoritatively,
)
from tests.ace.tui._artifacts_post_paint_publication_recovery import (
    test_cold_identity_not_called_during_construction,
    test_open_help_and_palette_refresh_on_publication,
    test_provider_removal_while_selected_falls_back_to_default,
    test_publication_covers_files_flag,
    test_publication_covers_retired_agent_flag,
    test_retry_after_failed_discovery_retains_generation,
    test_shutdown_before_completion_discards_late_result,
)
from tests.ace.tui._artifacts_post_paint_publication_replacement import (
    test_healthy_provider_is_replaced_when_it_degrades,
    test_partial_mount_failure_discards_staged_and_retries,
    test_unchanged_widgets_are_retained_across_generations,
)
from tests.ace.tui._artifacts_post_paint_publication_staging import (
    test_cold_nonempty_agents_identity_runs_after_first_paint_off_pump,
    test_leave_and_return_does_not_revive_pending_provider_jump,
    test_open_help_contents_include_published_provider,
    test_open_palette_selects_newly_published_command,
    test_scope_change_during_staging_is_applied_before_commit,
    test_stale_epoch_is_rejected_then_coalesced,
    test_teardown_during_mount_discards_staged_widgets,
)

__all__ = [
    "test_cold_identity_not_called_during_construction",
    "test_cold_nonempty_agents_identity_runs_after_first_paint_off_pump",
    "test_construction_uses_bootstrap_without_synchronous_discovery",
    "test_first_paint_fixed_panes_then_one_coherent_publication",
    "test_healthy_provider_is_replaced_when_it_degrades",
    "test_hidden_agents_startup_publishes_without_losing_selection",
    "test_leave_and_return_does_not_revive_pending_provider_jump",
    "test_open_help_and_palette_refresh_on_publication",
    "test_open_help_contents_include_published_provider",
    "test_open_palette_selects_newly_published_command",
    "test_partial_mount_failure_discards_staged_and_retries",
    "test_pending_digit_without_target_does_nothing",
    "test_pending_provider_jump_applies_only_without_supersede",
    "test_provider_removal_while_selected_falls_back_to_default",
    "test_publication_covers_files_flag",
    "test_publication_covers_retired_agent_flag",
    "test_render_and_catalog_builders_take_snapshot_without_discovery",
    "test_retry_after_failed_discovery_retains_generation",
    "test_scope_change_during_staging_is_applied_before_commit",
    "test_shutdown_before_completion_discards_late_result",
    "test_stale_epoch_is_rejected_then_coalesced",
    "test_teardown_during_mount_discards_staged_widgets",
    "test_unchanged_widgets_are_retained_across_generations",
    "test_user_navigation_supersedes_pending_provider_jump",
    "test_zero_providers_completes_authoritatively",
]
