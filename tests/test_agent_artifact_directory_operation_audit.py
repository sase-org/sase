"""Audit whole-directory operations that may affect agent marker files."""

from __future__ import annotations

from tests._agent_artifact_marker_audit_helpers import (
    _DELETE_INDEX,
    BatchedCoverage,
    DirOpReview,
    _artifact_directory_operation_contexts,
    _context_call_names,
)

_REVIEWED_DIR_OPERATION_CONTEXTS: dict[str, DirOpReview] = {
    "src/sase/ace/tui/bgcmd.py:clear_slot": DirOpReview(
        exemption=(
            "bgcmd slot directory under the ace TUI workspace, not a tracked "
            "agent artifact directory."
        ),
    ),
    "src/sase/agents/cli_artifacts_layout.py:_handle_migrate": DirOpReview(
        exemption=(
            "Moves flat ace-run artifact directories into the sharded physical "
            "layout, rewrites owned marker path fields, writes alias rows, and "
            "rebuilds the artifact index after the batch."
        ),
    ),
    "src/sase/agents/cli_artifacts_layout.py:_handle_rollback": DirOpReview(
        exemption=(
            "Moves sharded ace-run artifact directories back using a migration "
            "manifest, rewrites owned marker path fields, removes alias rows, "
            "and rebuilds the artifact index after the batch."
        ),
    ),
    "src/sase/agents/index_repair.py:_remove_artifacts": DirOpReview(
        batched_by=(
            BatchedCoverage(
                caller_context=(
                    "src/sase/agents/index_repair.py:apply_imported_state_repair"
                ),
                helper_call="_remove_artifacts",
                lifecycle_call=_DELETE_INDEX,
            ),
        ),
    ),
    "src/sase/agents/index_repair.py:_remove_journals_and_staging": DirOpReview(
        exemption=(
            "Removes only the selected import transaction's staging directory "
            "after deleting its journal so recovery cannot resurrect the "
            "future-dated imported state; it is not an agent artifact directory."
        ),
    ),
    "src/sase/agents_sync/bundles.py:_create_imported_artifact": DirOpReview(
        lifecycle_calls=("update_agent_artifact_index_for_marker_mutation",),
    ),
    "src/sase/agents_sync/git_sync_ops.py:ensure_agents_clone": DirOpReview(
        exemption=(
            "Atomically publishes a freshly cloned agents sidecar checkout and "
            "removes only its temporary clone staging directory, not an agent "
            "artifact directory."
        ),
    ),
    "src/sase/agents_sync/incoming_cache_storage.py:prune_project_cache": DirOpReview(
        exemption=(
            "Enumerates and removes only immutable incoming-sync cache objects "
            "under SASE_HOME/agents_sync/cache/objects after preserving pending, "
            "receipt, and recent superseded evidence; these are not local agent "
            "artifact directories."
        ),
    ),
    "src/sase/agents_sync/incoming_cache_storage.py:publish_cache_object": DirOpReview(
        exemption=(
            "Atomically promotes a validated incoming-sync cache staging directory "
            "and removes only that task-owned staging path; neither path is a "
            "local agent artifact directory."
        ),
    ),
    "src/sase/agents_sync/incoming_cache_storage.py:validate_unpublished_cache_payload": (
        DirOpReview(
            exemption=(
                "Creates and removes only a transient incoming-sync validation "
                "directory under SASE_HOME/agents_sync/cache/staging, not a local "
                "agent artifact directory."
            ),
        )
    ),
    "src/sase/dev_update/prebuild_producer.py:produce_prebuild": DirOpReview(
        exemption=(
            "Removes only an incomplete Rust prebuild cache staging directory "
            "under SASE_HOME/cache/rust-prebuild, not an agent artifact "
            "directory."
        ),
    ),
    "src/sase/dev_update/prebuild_producer.py:_prune_completed_sets": DirOpReview(
        exemption=(
            "Prunes only completed and temporary Rust prebuild cache sets under "
            "SASE_HOME/cache/rust-prebuild, not agent artifact directories."
        ),
    ),
    "src/sase/agents_sync/v1_retirement.py:_apply_v1_retirement": DirOpReview(
        exemption=(
            "Removes only evidence-covered legacy-v1 transport bundles inside "
            "an agents sidecar checkout, not local agent artifact directories."
        ),
    ),
    "src/sase/agents_sync/v2_io.py:apply_payload_atomic": DirOpReview(
        exemption=(
            "Atomically promotes validated owner-sharded payload files inside "
            "an agents sidecar and removes only its task-owned staging and "
            "rollback directories, never a local agent artifact directory."
        ),
    ),
    (
        "src/sase/agents_sync/v2_import_transactions.py:apply_and_finalize_transaction"
    ): DirOpReview(
        exemption=(
            "Removes only the completed transaction's staging directory after "
            "artifact and dismissed-index lifecycle updates have finished."
        ),
    ),
    "src/sase/agents_sync/v2_import_transactions.py:prepare_transaction": DirOpReview(
        exemption=(
            "Removes only a stale transaction-owned staging directory before "
            "restaging; it does not remove a local agent artifact directory."
        ),
    ),
    (
        "src/sase/agents_sync/v2_import_transactions.py:recover_v2_import_transactions"
    ): DirOpReview(
        exemption=(
            "Rolls back only the transaction-owned staging directory for a "
            "prepared journal; applied transactions resume normal finalization."
        ),
    ),
    "src/sase/agent/names/_wipe.py:_remove_artifact_dirs": DirOpReview(
        batched_by=(
            BatchedCoverage(
                caller_context=(
                    "src/sase/agent/names/_wipe.py:wipe_agent_name_for_reuse"
                ),
                helper_call="_remove_artifact_dirs",
                lifecycle_call=_DELETE_INDEX,
            ),
        ),
    ),
    "src/sase/axe/run_agent_exec_attempts.py:snapshot_attempt": DirOpReview(
        exemption=(
            "Operates on the attempts/<N>.tmp staging directory: shutil.rmtree "
            "removes a stale tmp dir, shutil.move relocates the live_reply "
            "byproducts into it, and os.rename promotes it to attempts/<N>/. "
            "None of these touch the tracked marker layer."
        ),
    ),
    "src/sase/core/managed_tmp_reaper.py:_remove_if_stale": DirOpReview(
        batched_by=(
            BatchedCoverage(
                caller_context="src/sase/core/managed_tmp_reaper.py:reap_managed_tmpdir",
                helper_call="_remove_if_stale",
                lifecycle_call=_DELETE_INDEX,
            ),
        ),
    ),
    "src/sase/llm_provider/_plan_utils.py:move_plan_to_sase": DirOpReview(
        exemption=(
            "Moves a submitted scratch plan file into the machine-local "
            "~/.sase/plans/YYYYMM/ archive, not an agent artifact directory."
        ),
    ),
    "src/sase/llm_provider/codex.py:_codex_subprocess_env": DirOpReview(
        exemption="Shadow CODEX_HOME cache, not an agent artifact directory.",
    ),
    "src/sase/_linked_repo_workspaces.py:_remove_path": DirOpReview(
        exemption=(
            "Removes only host-scoped repository paths under sase/repos or "
            "deferred-delete entries under .sase/trash, not agent artifact "
            "directories."
        ),
    ),
    "src/sase/_linked_repo_workspaces.py:clear_workspace_repos": DirOpReview(
        exemption=(
            "Moves the launch-scoped sase/repos tree into .sase/trash for "
            "detached deletion; neither path is an agent artifact directory."
        ),
    ),
    "src/sase/main/workspace_handler_migration.py:handle_migrate": DirOpReview(
        exemption=(
            "Moves a workspace checkout directory under a managed root, not an "
            "agent artifact directory."
        ),
    ),
    "src/sase/main/workspace_handler_maintenance.py:remove_checkout": DirOpReview(
        exemption=(
            "Removes a workspace checkout directory, not an agent artifact directory."
        ),
    ),
    "src/sase/mode_switch/execute.py:_cleanup_failed_clone": DirOpReview(
        exemption=(
            "Removes only a just-created failed dev checkout clone under "
            "update.dev_root, not an agent artifact directory."
        ),
    ),
    "src/sase/notification_gates/command_runner.py:_remove_untrusted_terminal": DirOpReview(
        exemption=(
            "Removes only an untrusted response/cancellation path created inside "
            "a SASE-owned interaction_requests bundle by its command; interaction "
            "bundles are not agent artifact directories."
        ),
    ),
    "src/sase/notification_gates/service.py:_start_gate_creation": DirOpReview(
        exemption=(
            "Compensates an unpublished interaction_requests bundle after gate "
            "creation fails; interaction bundles are not agent artifact directories."
        ),
    ),
    "src/sase/notification_gates/service.py:create_gate": DirOpReview(
        exemption=(
            "Repairs an initializing or failed interaction_requests bundle before "
            "retry; interaction bundles are not agent artifact directories."
        ),
    ),
    "src/sase/procs/_migration.py:_perform_migration": DirOpReview(
        exemption=(
            "Relocates the legacy ~/.sase/tasks proc-store logs directory to "
            "~/.sase/procs during the one-shot rename migration, not an agent "
            "artifact directory."
        ),
    ),
    "src/sase/sdd/_store_adoption.py:cleanup_staging": DirOpReview(
        exemption=(
            "Removes only provider-owned SDD materialization staging and recovery "
            "paths under a workspace's .sase directory, not agent artifact "
            "directories."
        ),
    ),
    "src/sase/sdd/_bead_adoption.py:_copy_bead_state": DirOpReview(
        exemption=(
            "Replaces only matching entries while importing the plans-owned bead "
            "store into its dedicated sidecar, not agent artifact directories."
        ),
    ),
    "src/sase/sdd/_bead_adoption.py:cleanup_plans_bead_state": DirOpReview(
        exemption=(
            "Removes only the legacy plans-sidecar bead-store directory after the "
            "dedicated beads sidecar becomes authoritative, not agent artifacts."
        ),
    ),
    "src/sase/sdd/_store_link.py:_handle_failed_sdd_clone": DirOpReview(
        exemption=(
            "Removes only partial output from a failed sidecar git clone at its "
            "workspace-local repository target, not an agent artifact directory."
        ),
    ),
    "src/sase/sdd/_store_link.py:_replace_workspace_sdd_clone": DirOpReview(
        exemption=(
            "Removes only the recovery copy left after atomically replacing a "
            "workspace-local SDD sidecar clone, not an agent artifact directory."
        ),
    ),
    "src/sase/main/project_handler.py:delete_project_locked": DirOpReview(
        exemption=(
            "Deletes the entire SASE project state directory only after blocking "
            "live RUNNING claims and live artifact markers; project-local "
            "artifacts and indexes are removed together with the project state."
        ),
    ),
    "src/sase/main/repo_open_external.py:_remove_clone_staging_path": DirOpReview(
        exemption=(
            "Removes only a just-created external-repo clone staging path under "
            "the host workspace's sase/repos/external tree, not an agent artifact "
            "directory."
        ),
    ),
    "src/sase/workspace_provider/utils.py:ensure_git_clone_at": DirOpReview(
        exemption=(
            "Workspace checkout directory under a managed root, not an agent "
            "artifact directory."
        ),
    ),
}


def test_artifact_directory_operation_sites_are_reviewed() -> None:
    assert set(_artifact_directory_operation_contexts()) == set(
        _REVIEWED_DIR_OPERATION_CONTEXTS
    )


def test_reviewed_dir_operation_sites_declare_coverage() -> None:
    for context, review in _REVIEWED_DIR_OPERATION_CONTEXTS.items():
        kinds = sum(
            bool(kind)
            for kind in (
                review.lifecycle_calls,
                review.batched_by,
                review.delegated,
                review.exemption,
            )
        )
        assert kinds == 1, context

        for coverage in review.batched_by:
            caller_calls = _context_call_names(coverage.caller_context)
            assert coverage.helper_call in caller_calls, coverage
            assert coverage.lifecycle_call in caller_calls, coverage

        if review.delegated is not None:
            caller_calls = _context_call_names(review.delegated.caller_context)
            assert review.delegated.helper_call in caller_calls, review.delegated

        if review.exemption:
            assert review.exemption.strip(), context
