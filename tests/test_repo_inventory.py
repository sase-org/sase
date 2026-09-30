"""Repository inventory domain coverage.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_repo_inventory_basic import (
    test_explicit_disabled_project_is_included,
    test_inventory_collects_all_repo_kinds_and_sidecar_wins_overlap,
    test_inventory_surfaces_configured_sidecar_role_and_slug,
    test_repo_display_name_prefers_slug_then_name,
)
from tests.test_repo_inventory_sidecars import (
    test_disabled_configured_sidecar_suppresses_store_record,
    test_inventory_dedupes_agents_row_when_store_record_lists_it,
    test_inventory_defaults_beads_lazy_and_plans_eager_without_explicit_config,
    test_inventory_exposes_hidden_agents_at_one_machine_level_path,
    test_inventory_exposes_hidden_attachments_private_at_machine_level_path,
    test_inventory_gates_beads_auto_clone_on_store_record,
    test_inventory_omits_unmanaged_or_disabled_agents_sidecar,
    test_pinned_sidecar_identity_overrides_stale_store_repo,
)
from tests.test_repo_inventory_workspaces import (
    test_inventory_joins_registered_workspace_clone_matrix,
    test_inventory_scans_external_repos_across_registered_workspaces,
)

__test__ = False

__all__ = [
    "test_disabled_configured_sidecar_suppresses_store_record",
    "test_explicit_disabled_project_is_included",
    "test_inventory_collects_all_repo_kinds_and_sidecar_wins_overlap",
    "test_inventory_dedupes_agents_row_when_store_record_lists_it",
    "test_inventory_defaults_beads_lazy_and_plans_eager_without_explicit_config",
    "test_inventory_exposes_hidden_agents_at_one_machine_level_path",
    "test_inventory_exposes_hidden_attachments_private_at_machine_level_path",
    "test_inventory_gates_beads_auto_clone_on_store_record",
    "test_inventory_joins_registered_workspace_clone_matrix",
    "test_inventory_omits_unmanaged_or_disabled_agents_sidecar",
    "test_inventory_scans_external_repos_across_registered_workspaces",
    "test_inventory_surfaces_configured_sidecar_role_and_slug",
    "test_pinned_sidecar_identity_overrides_stale_store_repo",
    "test_repo_display_name_prefers_slug_then_name",
]
