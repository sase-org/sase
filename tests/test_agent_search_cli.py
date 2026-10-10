"""Facade preserving the public import path for agent search CLI tests."""

from tests._agent_search_cli_archive import (
    test_agent_search_archive_cli_matches_shared_corpus_order,
)
from tests._agent_search_cli_output import (
    test_agent_search_pretty_output_smoke,
    test_agent_search_warns_when_catalog_enrichment_is_degraded,
)
from tests._agent_search_cli_parser import (
    test_agent_search_boolean_dialect_has_no_leading_dash_spelling,
    test_agent_search_parser_accepts_options_before_and_after_query,
    test_agent_search_parser_and_help_are_complete_and_sorted,
    test_agent_search_handles_options_parsed_after_the_query,
    test_agent_search_query_followed_by_limit_flag_does_not_hit_tokenizer_error,
)
from tests._agent_search_cli_query import (
    test_agent_catalog_query_entry_emits_stable_rust_wire_shape,
    test_agent_search_default_scope_excludes_hidden_and_workflow_children,
    test_agent_search_filters_artifact_link_facets,
    test_agent_search_inbox_scope_restricts_catalog_to_non_dismissed_rows,
    test_agent_search_json_filters_with_shared_profile,
    test_agent_search_legacy_family_terms_are_accepted_aliases,
    test_agent_search_rejects_invalid_in_token,
    test_agent_search_scope_hints_name_the_other_profile_field,
    test_agent_search_session_field_and_kind_match_session_rows,
)

__all__ = (
    "test_agent_search_parser_and_help_are_complete_and_sorted",
    "test_agent_search_parser_accepts_options_before_and_after_query",
    "test_agent_search_boolean_dialect_has_no_leading_dash_spelling",
    "test_agent_search_handles_options_parsed_after_the_query",
    "test_agent_search_query_followed_by_limit_flag_does_not_hit_tokenizer_error",
    "test_agent_search_json_filters_with_shared_profile",
    "test_agent_catalog_query_entry_emits_stable_rust_wire_shape",
    "test_agent_search_default_scope_excludes_hidden_and_workflow_children",
    "test_agent_search_filters_artifact_link_facets",
    "test_agent_search_inbox_scope_restricts_catalog_to_non_dismissed_rows",
    "test_agent_search_scope_hints_name_the_other_profile_field",
    "test_agent_search_archive_cli_matches_shared_corpus_order",
    "test_agent_search_rejects_invalid_in_token",
    "test_agent_search_pretty_output_smoke",
    "test_agent_search_warns_when_catalog_enrichment_is_degraded",
    "test_agent_search_session_field_and_kind_match_session_rows",
    "test_agent_search_legacy_family_terms_are_accepted_aliases",
)
