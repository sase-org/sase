"""Tests for ``sase artifact link add/list/rm``.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.main.test_artifact_cli_link_add import (
    test_absent_remove_retries_unpublished_tombstone,
    test_add_and_rm_work_without_feature_override,
    test_add_artifact_link_requires_reason,
    test_add_list_rm_round_trip,
    test_add_rejects_reserved_and_machine_relations,
    test_unchanged_add_retries_unpublished_partial_root,
)
from tests.main.test_artifact_cli_link_import import (
    test_import_indexes_apply_requires_matching_attestation,
    test_migrate_notes_apply_and_dry_run_succeed,
)
from tests.main.test_artifact_cli_link_list import (
    test_list_reads_rows_without_feature_override,
    test_list_source_store_reads_durable_rows_when_index_is_stale,
    test_list_without_reference_merges_in_projected_rows,
)
from tests.main.test_artifact_cli_link_relation import (
    test_parser_link_add_uses_positionals,
    test_parser_link_list_accepts_source,
    test_parser_link_relation_bare_defaults_to_list,
    test_parser_link_relation_show_uses_positional,
    test_relation_dispatch_defaults_to_usage_without_subcommand,
    test_relation_list_covers_every_builtin_slug,
    test_relation_show_json_emits_full_registry_entry,
    test_relation_show_prints_direction_and_examples,
    test_relation_show_unknown_slug_errors,
)

__test__ = False

__all__ = [
    "test_absent_remove_retries_unpublished_tombstone",
    "test_add_and_rm_work_without_feature_override",
    "test_add_artifact_link_requires_reason",
    "test_add_list_rm_round_trip",
    "test_add_rejects_reserved_and_machine_relations",
    "test_import_indexes_apply_requires_matching_attestation",
    "test_list_reads_rows_without_feature_override",
    "test_list_source_store_reads_durable_rows_when_index_is_stale",
    "test_list_without_reference_merges_in_projected_rows",
    "test_migrate_notes_apply_and_dry_run_succeed",
    "test_parser_link_add_uses_positionals",
    "test_parser_link_list_accepts_source",
    "test_parser_link_relation_bare_defaults_to_list",
    "test_parser_link_relation_show_uses_positional",
    "test_relation_dispatch_defaults_to_usage_without_subcommand",
    "test_relation_list_covers_every_builtin_slug",
    "test_relation_show_json_emits_full_registry_entry",
    "test_relation_show_prints_direction_and_examples",
    "test_relation_show_unknown_slug_errors",
    "test_unchanged_add_retries_unpublished_partial_root",
]
