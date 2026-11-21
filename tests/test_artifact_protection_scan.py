"""Artifact protection scan domain coverage.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_artifact_protection_scan_beads import (
    test_bead_ref_stays_protected_after_projection_is_gone,
    test_bead_store_projection_is_not_scanned_under_other_sidecar_roles,
    test_bead_store_projection_protects_refs_without_a_published_page,
    test_collects_and_normalizes_project_plan_bead_and_research_refs,
)
from tests.test_artifact_protection_scan_consumption import (
    test_artifact_link_aggregate_protects_linked_file_ids,
    test_consumption_adds_only_canonical_file_ids_and_retains_overlap_evidence,
    test_missing_consumption_ledger_is_an_empty_optional_source,
    test_query_failure_marks_present_consumption_ledger_unavailable,
)
from tests.test_artifact_protection_scan_scanning import (
    test_extract_artifact_ids_matches_expected_cases,
    test_projects_tree_scan_finds_spec_and_prunes_shared_dirs,
    test_projects_tree_walk_skips_artifacts_repos_and_git,
    test_scan_root_does_not_descend_symlinked_dirs,
)
from tests.test_artifact_protection_scan_sidecars import (
    test_connected_project_with_a_missing_clone_keeps_the_bare_label,
    test_managed_unconnected_project_reports_both_required_roles,
    test_missing_required_sidecar_is_unavailable_but_research_is_optional,
    test_unmanaged_project_with_live_beads_clone_is_scanned,
    test_unmanaged_unconnected_project_has_no_required_sources,
)

__test__ = False

__all__ = [
    "test_artifact_link_aggregate_protects_linked_file_ids",
    "test_bead_ref_stays_protected_after_projection_is_gone",
    "test_bead_store_projection_is_not_scanned_under_other_sidecar_roles",
    "test_bead_store_projection_protects_refs_without_a_published_page",
    "test_collects_and_normalizes_project_plan_bead_and_research_refs",
    "test_connected_project_with_a_missing_clone_keeps_the_bare_label",
    "test_consumption_adds_only_canonical_file_ids_and_retains_overlap_evidence",
    "test_extract_artifact_ids_matches_expected_cases",
    "test_managed_unconnected_project_reports_both_required_roles",
    "test_missing_consumption_ledger_is_an_empty_optional_source",
    "test_missing_required_sidecar_is_unavailable_but_research_is_optional",
    "test_projects_tree_scan_finds_spec_and_prunes_shared_dirs",
    "test_projects_tree_walk_skips_artifacts_repos_and_git",
    "test_query_failure_marks_present_consumption_ledger_unavailable",
    "test_scan_root_does_not_descend_symlinked_dirs",
    "test_unmanaged_project_with_live_beads_clone_is_scanned",
    "test_unmanaged_unconnected_project_has_no_required_sources",
]
