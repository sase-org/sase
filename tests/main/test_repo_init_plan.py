"""Tests for the ``sase repo init`` planner."""

from tests.main._test_repo_init_plan_management import (
    test_init_registry_uses_repo_runner,
    test_invalid_management_config_blocks_before_provider_calls,
    test_materialized_sidecar_run_still_fails_without_a_project_key,
    test_missing_attachments_private_plans_warning_not_action,
    test_plan_new_project_previews_newly_declared_research_sidecar,
    test_plan_non_project_reports_blocker,
    test_plan_skips_agents_sidecar_without_a_resolvable_project_key,
    test_plan_upgrade_previews_research_declaration_and_creation,
    test_run_uses_materialized_path_and_updates_project_wiring,
    test_unmanaged_apply_skips_before_store_materialization,
    test_unmanaged_check_is_informative_and_successful,
    test_unmanaged_plan_skips_before_provider_calls,
)
from tests.main._test_repo_init_plan_sidecars import (
    test_configured_sidecar_specs_preserve_pin_and_private_visibility,
    test_configured_sidecar_specs_suppress_disabled_agents,
    test_plan_does_not_materialize_recorded_lazy_sidecar_for_check,
    test_plan_github_reports_every_configured_sidecar_without_writing,
    test_plan_providerless_project_includes_store_config_and_ignore_actions,
    test_plan_reports_asset_only_agents_guide_refresh,
    test_plan_reports_pending_bead_state_adoption,
)

__all__ = [
    "test_configured_sidecar_specs_preserve_pin_and_private_visibility",
    "test_configured_sidecar_specs_suppress_disabled_agents",
    "test_init_registry_uses_repo_runner",
    "test_invalid_management_config_blocks_before_provider_calls",
    "test_materialized_sidecar_run_still_fails_without_a_project_key",
    "test_missing_attachments_private_plans_warning_not_action",
    "test_plan_does_not_materialize_recorded_lazy_sidecar_for_check",
    "test_plan_github_reports_every_configured_sidecar_without_writing",
    "test_plan_new_project_previews_newly_declared_research_sidecar",
    "test_plan_non_project_reports_blocker",
    "test_plan_providerless_project_includes_store_config_and_ignore_actions",
    "test_plan_reports_asset_only_agents_guide_refresh",
    "test_plan_reports_pending_bead_state_adoption",
    "test_plan_skips_agents_sidecar_without_a_resolvable_project_key",
    "test_plan_upgrade_previews_research_declaration_and_creation",
    "test_run_uses_materialized_path_and_updates_project_wiring",
    "test_unmanaged_apply_skips_before_store_materialization",
    "test_unmanaged_check_is_informative_and_successful",
    "test_unmanaged_plan_skips_before_provider_calls",
]
