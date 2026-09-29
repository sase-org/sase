"""Tests for forced-reuse agent-name wipe semantics.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_agent_name_wipe_basic import (
    test_batch_wipe_shares_catalog_and_registry_rebuild,
    test_release_artifact_workspace_ignores_index_refresh_failure,
    test_release_artifact_workspace_updates_index_after_running_marker_delete,
    test_wipe_deletes_artifact_index_rows_for_removed_dirs,
    test_wipe_dismissed_bundle_only_agent_removes_bundle_and_index,
    test_wipe_done_agent_clears_lookup_registry_and_notifications,
    test_wipe_retry_chain_and_bundle_descendants,
    test_wipe_workflow_parent_removes_children_and_followups,
)
from tests.test_agent_name_wipe_live import (
    test_wipe_live_agent_keeps_artifact_when_stop_is_unverified,
    test_wipe_live_agent_terminates_and_releases_workspace,
    test_wipe_live_agent_waits_for_real_process_exit_before_removal,
)
from tests.test_agent_name_wipe_sessions import (
    test_forced_reuse_owners_raise_and_delete_nothing_on_session_root_leak,
    test_wipe_agent_session_member_finds_day_sharded_handoff_and_bundle,
    test_wipe_auto_code_member_keeps_root_whose_done_marker_names_it,
    test_wipe_code_member_preserves_plan_member_and_agent_session_container,
    test_wipe_container_name_preserves_member_artifacts_and_registry,
    test_wipe_refuses_member_closure_that_reaches_session_root,
    test_wipe_whole_agent_session_batch_still_removes_root_and_members,
)

__test__ = False

__all__ = [
    "test_batch_wipe_shares_catalog_and_registry_rebuild",
    "test_forced_reuse_owners_raise_and_delete_nothing_on_session_root_leak",
    "test_release_artifact_workspace_ignores_index_refresh_failure",
    "test_release_artifact_workspace_updates_index_after_running_marker_delete",
    "test_wipe_agent_session_member_finds_day_sharded_handoff_and_bundle",
    "test_wipe_auto_code_member_keeps_root_whose_done_marker_names_it",
    "test_wipe_code_member_preserves_plan_member_and_agent_session_container",
    "test_wipe_container_name_preserves_member_artifacts_and_registry",
    "test_wipe_deletes_artifact_index_rows_for_removed_dirs",
    "test_wipe_dismissed_bundle_only_agent_removes_bundle_and_index",
    "test_wipe_done_agent_clears_lookup_registry_and_notifications",
    "test_wipe_live_agent_keeps_artifact_when_stop_is_unverified",
    "test_wipe_live_agent_terminates_and_releases_workspace",
    "test_wipe_live_agent_waits_for_real_process_exit_before_removal",
    "test_wipe_refuses_member_closure_that_reaches_session_root",
    "test_wipe_retry_chain_and_bundle_descendants",
    "test_wipe_whole_agent_session_batch_still_removes_root_and_members",
    "test_wipe_workflow_parent_removes_children_and_followups",
]
