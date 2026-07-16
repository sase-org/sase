"""Audit mutation sites for Tier 1-projected agent markers.

Fail-closed AST audit for functions that contain a tracked marker filename
literal and a direct mutation call. Every reviewed entry must declare exactly
one coverage shape: direct lifecycle calls, batched lifecycle coverage,
delegation to another reviewed context, or an exemption.

Lifecycle helpers live in
``src/sase/core/agent_artifact_index_lifecycle.py`` and are the only
authorized way to keep the Tier 1 SQLite index in sync with a marker mutation:

- ``update_agent_artifact_index_for_marker_mutation``
- ``upsert_agent_artifact_index_artifacts``
- ``delete_agent_artifact_index_artifacts``
- ``sync_dismissed_agent_artifact_index``
"""

from __future__ import annotations

from tests._agent_artifact_marker_audit_helpers import (
    _DELETE_INDEX,
    _UPDATE_INDEX,
    _UPSERT_INDEX,
    BatchedCoverage,
    DelegatedCoverage,
    Review,
    _context_call_names,
    _has_lifecycle_coverage,
    _marker_mutation_contexts,
)

_REVIEWED_MARKER_MUTATION_CONTEXTS: dict[str, Review] = {
    (
        "src/sase/ace/tui/actions/agents/_directive_persistence.py:_patch_agent_meta"
    ): Review(
        mutation_calls=("_write_json_file",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    (
        "src/sase/ace/tui/actions/agents/_directive_persistence.py:"
        "_write_waiting_marker"
    ): Review(
        mutation_calls=("_write_json_file",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/ace/tui/actions/agents/_killing_utils.py:delete_agent_artifacts": Review(
        mutation_calls=("unlink",),
        lifecycle_calls=(_DELETE_INDEX,),
    ),
    (
        "src/sase/ace/tui/actions/agents/_killing_utils.py:"
        "_resolve_waiters_before_artifact_delete"
    ): Review(
        mutation_calls=("open", "dump", "open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    (
        "src/sase/ace/tui/actions/agents/_notification_plan_persistence.py:"
        "persist_plan_approved"
    ): Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    (
        "src/sase/ace/tui/actions/agents/_revive_artifacts.py:_restore_agent_artifacts"
    ): Review(
        mutation_calls=("write_text", "write_text", "write_text", "write_text"),
        batched_by=(
            BatchedCoverage(
                caller_context=(
                    "src/sase/ace/tui/actions/agents/"
                    "_revive_execution.py:_do_revive_agent"
                ),
                helper_call="_restore_agent_artifacts",
                lifecycle_call=_UPSERT_INDEX,
            ),
            BatchedCoverage(
                caller_context=(
                    "src/sase/ace/tui/actions/agents/"
                    "_revive_execution.py:_do_revive_agents"
                ),
                helper_call="_restore_agent_artifacts",
                lifecycle_call=_UPSERT_INDEX,
            ),
        ),
    ),
    "src/sase/ace/tui/actions/agents/_revive_artifacts.py:_restore_agent_meta": Review(
        mutation_calls=("write_text",),
        delegated=DelegatedCoverage(
            caller_context=(
                "src/sase/ace/tui/actions/agents/_revive_artifacts.py:"
                "_restore_agent_artifacts"
            ),
            helper_call="_restore_agent_meta",
            coverage_context=(
                "src/sase/ace/tui/actions/agents/_revive_artifacts.py:"
                "_restore_agent_artifacts"
            ),
        ),
    ),
    (
        "src/sase/ace/tui/models/_loaders/_running_loaders.py:"
        "load_running_home_agents_from_snapshot"
    ): Review(
        mutation_calls=("unlink",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    (
        "src/sase/ace/tui/models/_loaders/_running_loaders.py:load_running_home_agents"
    ): Review(
        mutation_calls=("unlink",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/agent/names/_migration.py:_rewrite_artifact_json_files": Review(
        mutation_calls=("_write_json_file", "_write_json_file"),
        batched_by=(
            BatchedCoverage(
                caller_context=(
                    "src/sase/agent/names/_migration.py:"
                    "run_historical_auto_name_migration"
                ),
                helper_call="_rewrite_artifact_json_files",
                lifecycle_call=_UPSERT_INDEX,
            ),
        ),
    ),
    "src/sase/agent/names/_wipe.py:_release_artifact_workspace": Review(
        mutation_calls=("unlink",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/agent/running.py:_remove_agent_state_markers": Review(
        mutation_calls=("unlink",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/bead/epic_launch.py:update_epic_launch_metadata": Review(
        mutation_calls=("write_text",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_directives.py:extract_directives_and_write_meta": Review(
        mutation_calls=("unlink",),
        delegated=DelegatedCoverage(
            caller_context=(
                "src/sase/axe/run_agent_directives.py:extract_directives_and_write_meta"
            ),
            helper_call="write_agent_meta",
            coverage_context="src/sase/axe/run_agent_markers.py:write_agent_meta",
        ),
    ),
    "src/sase/axe/run_agent_exec_markers.py:write_done_marker_and_update_index": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_exec_markers.py:update_workflow_pdf_status": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_exec_markers.py:clear_workflow_pdf_activity": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_exec_plan_artifacts.py:write_plan_path_artifact": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers_artifacts.py:append_meta_list_field": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers_artifacts.py:update_meta_field": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers_artifacts.py:update_meta_suffix": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers_artifacts.py:promote_to_workflow": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers_handoff.py:normalize_handoff_interruption_state": Review(
        mutation_calls=("open", "dump", "open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers_handoff.py:finalize_handoff_artifacts_as_completed": Review(
        mutation_calls=("open", "dump", "open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers_handoff.py:update_step_marker_chat_path": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers_artifacts.py:create_followup_artifacts": Review(
        mutation_calls=("open", "dump", "open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_helpers_questions.py:handle_questions_flow": Review(
        mutation_calls=("open", "dump", "open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    (
        "src/sase/axe/run_agent_helpers_questions.py:_remove_pending_question_marker"
    ): Review(
        mutation_calls=("unlink",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_markers.py:write_agent_meta": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_retry_spawn.py:mark_parent_retried": Review(
        mutation_calls=("write_text",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_runner_finalize.py:write_error_done_marker": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_runner_setup.py:setup_artifacts_directory": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_runner_setup.py:write_agent_meta": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_runner_setup.py:write_home_running_marker": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_wait.py:_write_waiting_marker": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_wait.py:_remove_waiting_marker": Review(
        mutation_calls=("unlink",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_agent_wait.py:wait_for_dependencies": Review(
        mutation_calls=(
            "unlink",
            "open",
            "dump",
            "unlink",
            "open",
            "dump",
            "unlink",
        ),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/run_workflow_runner.py:_write_workflow_state": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/runner_artifacts.py:write_agent_meta": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/runner_artifacts.py:clear_agent_meta_tag": Review(
        mutation_calls=("open", "dump", "os.replace", "unlink"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/axe/runner_artifacts.py:write_done_marker": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/workflows/commit/commit_tracking.py:_persist_commit_diff_path": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/plan_approval_actions.py:_persist_plan_approved_metadata": Review(
        mutation_calls=("write_text",),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/scripts/sase_chop_wait_checks.py:main": Review(
        mutation_calls=("open", "dump"),
        exemption=(
            "Writes ready.json success markers only; waiting.json and "
            "agent_meta.json are read inputs, and ready.json is not Tier 1 indexed."
        ),
    ),
    "src/sase/xprompt/workflow_executor.py:_save_state": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/xprompt/workflow_executor.py:_save_prompt_step_marker": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
    "src/sase/xprompt/workflow_runner.py:_write_failed_workflow_state": Review(
        mutation_calls=("open", "dump"),
        lifecycle_calls=(_UPDATE_INDEX,),
    ),
}


def test_tracked_marker_mutation_sites_are_reviewed() -> None:
    assert set(_marker_mutation_contexts()) == set(_REVIEWED_MARKER_MUTATION_CONTEXTS)


def test_reviewed_marker_mutation_sites_match_expected_mutations() -> None:
    contexts = _marker_mutation_contexts()
    expected = {
        context: review.mutation_calls
        for context, review in _REVIEWED_MARKER_MUTATION_CONTEXTS.items()
    }
    actual = {
        context: info.mutation_calls
        for context, info in contexts.items()
        if context in _REVIEWED_MARKER_MUTATION_CONTEXTS
    }
    assert actual == expected


def test_reviewed_marker_mutation_sites_declare_lifecycle_coverage() -> None:
    contexts = _marker_mutation_contexts()
    for context, review in _REVIEWED_MARKER_MUTATION_CONTEXTS.items():
        coverage_kinds = sum(
            bool(kind)
            for kind in (
                review.lifecycle_calls,
                review.batched_by,
                review.delegated,
                review.exemption,
            )
        )
        assert coverage_kinds == 1, context

        if review.lifecycle_calls:
            missing = set(review.lifecycle_calls) - set(
                contexts[context].lifecycle_calls
            )
            assert not missing, f"{context} is missing lifecycle calls: {missing}"

        for coverage in review.batched_by:
            caller_calls = _context_call_names(coverage.caller_context)
            assert coverage.helper_call in caller_calls, coverage
            assert coverage.lifecycle_call in caller_calls, coverage

        if review.delegated is not None:
            caller_calls = _context_call_names(review.delegated.caller_context)
            assert review.delegated.helper_call in caller_calls, review.delegated
            coverage_review = _REVIEWED_MARKER_MUTATION_CONTEXTS[
                review.delegated.coverage_context
            ]
            assert _has_lifecycle_coverage(coverage_review), review.delegated

        if review.exemption:
            assert review.exemption.strip(), context
