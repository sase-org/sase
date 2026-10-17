"""Clan detail-panel file-hint tests.

Split facade: the tests now live in ``test_agent_display_clan_hints_summary``,
``test_agent_display_clan_hints_render``, and
``test_agent_display_clan_hints_bodies`` (shared helpers in
``_agent_display_clan_hints_shared``). This module re-exports the public names
so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.widgets.test_agent_display_clan_hints_bodies import (
    test_clan_full_bodies_use_each_members_workspace,
    test_clan_full_sections_hint_values_and_bodies_but_not_variable_names,
    test_clan_level_two_hints_only_rendered_triage_entries,
    test_clan_member_bodies_share_one_hint_budget,
    test_clan_member_workspace_is_resolved_lazily_once,
)
from tests.ace.tui.widgets.test_agent_display_clan_hints_render import (
    test_clan_hint_render_preserves_folded_snapshot_structure,
    test_clan_hint_render_reports_loading_and_enriched_states,
    test_clan_member_jump_gutter_is_untouched_by_double_digit_hints,
    test_clan_slow_tool_hints_register_report_specs,
    test_clan_snapshot_merge_invalidates_cached_hint_document,
)
from tests.ace.tui.widgets.test_agent_display_clan_hints_summary import (
    test_clan_summary_matches_known_artifact_suffix,
    test_clan_summary_paths_render_ordered_hints_from_member_workspace,
    test_clan_summary_prefers_worker_resolved_plan_path,
    test_clan_summary_prompt_row_resolves_to_archived_prompt_index,
    test_clan_summary_skips_paths_inside_http_urls,
    test_clan_summary_styles_survive_hint_insertion,
    test_clan_summary_unindexed_prompt_is_not_hijacked_by_plan_suffix,
    test_clan_summary_unresolved_token_uses_workspace_fallback,
    test_fold_level_three_plan_context_hint_keeps_logical_identity,
    test_unindexed_logical_plan_hint_keeps_its_identity,
)

__test__ = False

__all__ = [
    "test_clan_full_bodies_use_each_members_workspace",
    "test_clan_full_sections_hint_values_and_bodies_but_not_variable_names",
    "test_clan_hint_render_preserves_folded_snapshot_structure",
    "test_clan_hint_render_reports_loading_and_enriched_states",
    "test_clan_level_two_hints_only_rendered_triage_entries",
    "test_clan_member_bodies_share_one_hint_budget",
    "test_clan_member_jump_gutter_is_untouched_by_double_digit_hints",
    "test_clan_member_workspace_is_resolved_lazily_once",
    "test_clan_slow_tool_hints_register_report_specs",
    "test_clan_snapshot_merge_invalidates_cached_hint_document",
    "test_clan_summary_matches_known_artifact_suffix",
    "test_clan_summary_paths_render_ordered_hints_from_member_workspace",
    "test_clan_summary_prefers_worker_resolved_plan_path",
    "test_clan_summary_prompt_row_resolves_to_archived_prompt_index",
    "test_clan_summary_skips_paths_inside_http_urls",
    "test_clan_summary_styles_survive_hint_insertion",
    "test_clan_summary_unindexed_prompt_is_not_hijacked_by_plan_suffix",
    "test_clan_summary_unresolved_token_uses_workspace_fallback",
    "test_fold_level_three_plan_context_hint_keeps_logical_identity",
    "test_unindexed_logical_plan_hint_keeps_its_identity",
]
