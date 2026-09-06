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
    "src/sase/agents_sync/git_sync_ops.py:ensure_agents_clone": DirOpReview(
        exemption=(
            "Atomically publishes a freshly cloned agents sidecar checkout and "
            "removes only its temporary clone staging directory, not an agent "
            "artifact directory."
        ),
    ),
    "src/sase/agents_sync/purge_local_state.py:_apply_closure": DirOpReview(
        lifecycle_calls=(_DELETE_INDEX,),
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
    "src/sase/agents_sync/v2_io.py:apply_payload_atomic": DirOpReview(
        exemption=(
            "Atomically promotes validated owner-sharded payload files inside "
            "an agents sidecar and removes only its task-owned staging and "
            "rollback directories, never a local agent artifact directory."
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
    "src/sase/migration_kit/restore.py:_swap_into_place": DirOpReview(
        exemption=(
            "Moves a migration-kit declared source root aside (never deleting "
            "it) and swaps in a staged restore copy from the cutover backup "
            "root; operates only on the kit's declared roots and its own "
            "cutover staging tree outside SASE_HOME, never an agent artifact "
            "directory."
        ),
    ),
    "src/sase/migration_kit/atomic.py:_remove_path": DirOpReview(
        exemption=(
            "Removes only migration-kit temporary staging paths created in the "
            "destination directory for atomic writes and archive copies, not "
            "agent artifact directories."
        ),
    ),
    "src/sase/migration_kit/atomic.py:remove_path": DirOpReview(
        exemption=(
            "Removes only operation-declared residue after the migration driver "
            "has recorded a manifest, passed digest/backup gates, and promoted "
            "an archive copy; import-state artifact cleanup uses the reviewed "
            "purge-local-state path instead."
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
            "Creates ~/.sase/procs and relocates the legacy ~/.sase/tasks "
            "proc-store launch locks during the one-shot rename migration, not "
            "an agent artifact directory."
        ),
    ),
    "src/sase/procs/_migration.py:_relocate_legacy_logs": DirOpReview(
        exemption=(
            "Moves the legacy ~/.sase/tasks proc-store logs directory under "
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
    "src/sase/sdd/_store_clone_ops.py:_remove_partial_sdd_clone": DirOpReview(
        exemption=(
            "Removes only partial output between or after failed sidecar git clone "
            "attempts at the workspace-local repository target, not an agent "
            "artifact directory."
        ),
    ),
    "src/sase/sdd/_store_link.py:_replace_workspace_sdd_clone": DirOpReview(
        exemption=(
            "Removes only the recovery copy left after atomically replacing a "
            "workspace-local SDD sidecar clone, not an agent artifact directory."
        ),
    ),
    "src/sase/main/project_handler_lifecycle.py:delete_project_locked": DirOpReview(
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
    "src/sase/workspace_provider/reset_replay.py:_clear_owned_paths": DirOpReview(
        exemption=(
            "Clears only caller-supplied generated paths after reset-and-replay "
            "has authorized a live leased checkout; every path is refused unless "
            "it resolves under that leased checkout, so it never clears primary "
            "or local agent artifact directories outside the lease."
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
