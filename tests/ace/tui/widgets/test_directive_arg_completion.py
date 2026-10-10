"""Tests for prompt directive argument completion candidates.

Split facade: the tests now live in ``test_directive_arg_completion_fixed``,
``test_directive_arg_completion_wait``, and
``test_directive_arg_completion_model`` (shared helpers in
``_directive_completion_helpers``). This module re-exports the public names
so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.widgets.test_directive_arg_completion_fixed import (
    test_auto_argument_completion_suggests_compatibility_values_without_closing_parser,
    test_directive_arg_completion_accepts_effort_e_alias,
    test_directive_arg_completion_builds_fixed_value_candidates,
    test_directive_arg_completion_filters_case_insensitive_prefixes,
    test_directive_arg_completion_ignores_open_text_directives,
    test_directive_arg_completion_metadata_has_descriptions,
    test_legacy_enabled_directive_offers_bool_values,
    test_queue_capacity_completion_describes_limit,
    test_queue_priority_completion_describes_order_and_default,
    test_repeat_offers_positive_count_examples,
)
from tests.ace.tui.widgets.test_directive_arg_completion_model import (
    test_directive_arg_completion_builds_model_candidates_from_catalog,
    test_directive_arg_completion_filters_leading_at_to_model_aliases,
    test_directive_arg_completion_filters_model_candidates_by_short_alias,
    test_directive_arg_completion_filters_provider_scope_in_paren_forms,
    test_directive_arg_completion_filters_provider_scoped_models,
    test_directive_arg_completion_marks_provider_candidates_as_directories,
    test_model_alias_candidate_carries_resolution_and_provenance,
    test_model_candidate_preserves_structured_advisory_metadata,
    test_model_completion_keystroke_path_never_uses_override_lock,
    test_provider_scoped_model_completion_has_no_shared_extension,
    test_qualified_model_at_suffix_routes_to_effort_completion,
)
from tests.ace.tui.widgets.test_directive_arg_completion_wait import (
    test_clan_summary_conflict_omits_summary_script,
    test_id_clan_value_filters_to_clan_kind,
    test_id_conflict_omits_session_and_tribe_after_clan,
    test_id_session_value_filters_to_session_kind,
    test_wait_arg_completion_excludes_groups_and_deduplicates_insertions,
    test_wait_arg_completion_excludes_selected_keywords_case_insensitively,
    test_wait_arg_completion_filters_visible_agent_candidates,
    test_wait_arg_completion_ignores_time_keyword_fragment,
    test_wait_arg_completion_offers_deduplicated_tribe_targets,
    test_wait_arg_completion_omits_named_proc_targets,
    test_wait_arg_completion_orders_kinds_and_matches_bare_tribe,
    test_wait_bead_values_show_loading_when_catalog_is_cold,
    test_wait_bead_values_use_core_ranked_inventory,
    test_wait_paren_arg_completion_does_not_suggest_queue_keywords,
)

__test__ = False

__all__ = [
    "test_auto_argument_completion_suggests_compatibility_values_without_closing_parser",
    "test_clan_summary_conflict_omits_summary_script",
    "test_directive_arg_completion_accepts_effort_e_alias",
    "test_directive_arg_completion_builds_fixed_value_candidates",
    "test_directive_arg_completion_builds_model_candidates_from_catalog",
    "test_directive_arg_completion_filters_case_insensitive_prefixes",
    "test_directive_arg_completion_filters_leading_at_to_model_aliases",
    "test_directive_arg_completion_filters_model_candidates_by_short_alias",
    "test_directive_arg_completion_filters_provider_scope_in_paren_forms",
    "test_directive_arg_completion_filters_provider_scoped_models",
    "test_directive_arg_completion_ignores_open_text_directives",
    "test_directive_arg_completion_marks_provider_candidates_as_directories",
    "test_directive_arg_completion_metadata_has_descriptions",
    "test_id_clan_value_filters_to_clan_kind",
    "test_id_conflict_omits_session_and_tribe_after_clan",
    "test_id_session_value_filters_to_session_kind",
    "test_legacy_enabled_directive_offers_bool_values",
    "test_model_alias_candidate_carries_resolution_and_provenance",
    "test_model_candidate_preserves_structured_advisory_metadata",
    "test_model_completion_keystroke_path_never_uses_override_lock",
    "test_provider_scoped_model_completion_has_no_shared_extension",
    "test_qualified_model_at_suffix_routes_to_effort_completion",
    "test_queue_capacity_completion_describes_limit",
    "test_queue_priority_completion_describes_order_and_default",
    "test_repeat_offers_positive_count_examples",
    "test_wait_arg_completion_excludes_groups_and_deduplicates_insertions",
    "test_wait_arg_completion_excludes_selected_keywords_case_insensitively",
    "test_wait_arg_completion_filters_visible_agent_candidates",
    "test_wait_arg_completion_ignores_time_keyword_fragment",
    "test_wait_arg_completion_offers_deduplicated_tribe_targets",
    "test_wait_arg_completion_omits_named_proc_targets",
    "test_wait_arg_completion_orders_kinds_and_matches_bare_tribe",
    "test_wait_bead_values_show_loading_when_catalog_is_cold",
    "test_wait_bead_values_use_core_ranked_inventory",
    "test_wait_paren_arg_completion_does_not_suggest_queue_keywords",
]
