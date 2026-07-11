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
    "src/sase/llm_provider/_plan_utils.py:move_plan_to_sase": DirOpReview(
        exemption=(
            "Moves a submitted scratch plan file into the machine-local "
            "~/.sase/plans/YYYYMM/ archive, not an agent artifact directory."
        ),
    ),
    "src/sase/llm_provider/codex.py:_codex_subprocess_env": DirOpReview(
        exemption="Shadow CODEX_HOME cache, not an agent artifact directory.",
    ),
    "src/sase/linked_repos.py:_prepare_linked_repo_clone_dir": DirOpReview(
        exemption=(
            "Moves a host-scoped linked repository checkout from the legacy "
            ".sase/workspaces path to sase/repos, not an agent artifact directory."
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
    "src/sase/sdd/_store_adoption.py:cleanup_staging": DirOpReview(
        exemption=(
            "Removes only provider-owned SDD materialization staging and recovery "
            "paths under a workspace's .sase directory, not agent artifact "
            "directories."
        ),
    ),
    "src/sase/sdd/_store_link.py:_replace_workspace_sdd_clone": DirOpReview(
        exemption=(
            "Removes only the recovery copy left after atomically replacing a "
            "workspace-local SDD companion clone, not an agent artifact directory."
        ),
    ),
    "src/sase/main/project_handler.py:delete_project_locked": DirOpReview(
        exemption=(
            "Deletes the entire SASE project state directory only after blocking "
            "live RUNNING claims and live artifact markers; project-local "
            "artifacts and indexes are removed together with the project state."
        ),
    ),
    (
        "src/sase/telemetry/cli_export_config.py:handle_telemetry_export_config"
    ): DirOpReview(
        exemption=(
            "Telemetry export output directory, not an agent artifact directory."
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
