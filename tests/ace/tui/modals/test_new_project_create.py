"""Public import facade for new-project create tests.

The tests live in smaller neighboring modules; this module preserves their original
import path without collecting them a second time.
"""

from __future__ import annotations

__test__ = False

from ._new_project_create_helpers import fake_provider_fixture as fake_provider
from .test_new_project_create_defaults import (
    test_owner_defaults_prefer_last_used_then_project_then_account,
    test_owner_defaults_skip_unavailable_and_support_bare_git,
    test_visibility_defaults_to_private_then_last_supported_choice,
    test_supported_visibilities_follow_provider_choice_field,
    test_normalize_create_name_preserves_provider_identity,
    test_normalize_create_name_rejects_blank_and_unknown,
    test_normalized_label_shows_only_genuine_changes,
    test_normalize_bare_git_supports_empty_namespace,
    test_classify_probe_maps_all_states,
    test_probe_result_current_rejects_every_stale_dimension,
)
from .test_new_project_create_intent import (
    test_observe_checkout_reports_states_without_subprocesses,
    test_observe_checkout_matches_origin_identity,
    test_lenient_options_omit_unavailable_controls,
    test_build_create_plan_request_preserves_complete_intent,
    test_build_create_plan_request_reflects_bare_git_paths,
    test_plan_create_display_builds_mode_create_document,
    test_create_identity_verdict_reports_taken_and_invalid,
    test_add_instead_seed_preserves_canonical_target,
)
from .test_new_project_create_flow import (
    test_current_project_context_defaults_provider_and_owner,
    test_typing_starts_no_sync_probe_and_settles_once,
    test_project_name_follows_until_explicitly_edited,
    test_owner_switch_preserves_per_owner_drafts,
    test_taken_name_offers_explicit_add_instead,
    test_enter_with_available_name_creates_nothing,
    test_probe_failure_never_becomes_available,
    test_missing_form_leaves_no_confirmable_draft,
    test_name_collision_blocks_review_but_occupied_checkout_surfaces,
)
from .test_new_project_create_races import (
    test_late_form_completion_keeps_current_owner_edits,
    test_stale_probe_and_preview_results_are_discarded,
    test_back_cancels_pending_work,
    test_unmount_cancels_pending_timer,
    test_paste_in_create_stage_leaves_source_filter_alone,
    test_bare_git_entry_supports_empty_namespace,
)

__all__ = [
    "fake_provider",
    "test_owner_defaults_prefer_last_used_then_project_then_account",
    "test_owner_defaults_skip_unavailable_and_support_bare_git",
    "test_visibility_defaults_to_private_then_last_supported_choice",
    "test_supported_visibilities_follow_provider_choice_field",
    "test_normalize_create_name_preserves_provider_identity",
    "test_normalize_create_name_rejects_blank_and_unknown",
    "test_normalized_label_shows_only_genuine_changes",
    "test_normalize_bare_git_supports_empty_namespace",
    "test_classify_probe_maps_all_states",
    "test_probe_result_current_rejects_every_stale_dimension",
    "test_observe_checkout_reports_states_without_subprocesses",
    "test_observe_checkout_matches_origin_identity",
    "test_lenient_options_omit_unavailable_controls",
    "test_build_create_plan_request_preserves_complete_intent",
    "test_build_create_plan_request_reflects_bare_git_paths",
    "test_plan_create_display_builds_mode_create_document",
    "test_create_identity_verdict_reports_taken_and_invalid",
    "test_add_instead_seed_preserves_canonical_target",
    "test_current_project_context_defaults_provider_and_owner",
    "test_typing_starts_no_sync_probe_and_settles_once",
    "test_project_name_follows_until_explicitly_edited",
    "test_owner_switch_preserves_per_owner_drafts",
    "test_taken_name_offers_explicit_add_instead",
    "test_enter_with_available_name_creates_nothing",
    "test_probe_failure_never_becomes_available",
    "test_missing_form_leaves_no_confirmable_draft",
    "test_name_collision_blocks_review_but_occupied_checkout_surfaces",
    "test_late_form_completion_keeps_current_owner_edits",
    "test_stale_probe_and_preview_results_are_discarded",
    "test_back_cancels_pending_work",
    "test_unmount_cancels_pending_timer",
    "test_paste_in_create_stage_leaves_source_filter_alone",
    "test_bare_git_entry_supports_empty_namespace",
]
