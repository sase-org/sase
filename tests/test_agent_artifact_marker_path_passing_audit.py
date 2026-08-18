"""Audit tracked marker paths passed to non-safe callees."""

from __future__ import annotations

from tests._agent_artifact_marker_audit_helpers import (
    PathPassingReview,
    _path_passing_contexts,
)

_REVIEWED_PATH_PASSING_CONTEXTS: dict[str, PathPassingReview] = {
    "src/sase/agents_sync/bundles.py:_create_imported_artifact": PathPassingReview(
        lifecycle_coverage=(
            "Publishes imported agent_meta.json and done.json together, then "
            "refreshes the Tier 1 artifact index for the new artifact directory."
        ),
    ),
    "src/sase/agents_sync/bundles.py:_refresh_imported_artifact": PathPassingReview(
        lifecycle_coverage=(
            "Rewrites imported agent_meta.json and done.json, then refreshes "
            "the Tier 1 artifact index for the same artifact directory."
        ),
    ),
    "src/sase/agent/_family_promotion.py:promote_agent_to_family": PathPassingReview(
        lifecycle_coverage=(
            "Atomically rewrites agent_meta.json and immediately refreshes the "
            "Tier 1 artifact index for the same artifacts directory."
        ),
    ),
    "src/sase/axe/run_agent_wait_markers.py:remove_waiting_marker": PathPassingReview(
        lifecycle_coverage=(
            "Deletes waiting.json and immediately refreshes the Tier 1 artifact "
            "index for the same artifacts directory."
        ),
    ),
    "src/sase/agent/identity.py:require_agent_identity": PathPassingReview(
        exemption=(
            "Read-only audit attribution fallback: artifacts_dir is used only "
            "to discover an agent name from agent_meta.json."
        ),
    ),
    "src/sase/agent/restart.py:_write_recovery_files": PathPassingReview(
        exemption=(
            "Recovery-bundle snapshot: agent_meta.json is copied into "
            "~/.sase/restarts, not into a live artifact directory."
        ),
    ),
    "src/sase/agent/running.py:_read_cl_name_from_artifacts": PathPassingReview(
        exemption=(
            "Read-only kill attribution fallback: marker paths are used only "
            "to recover cl_name from agent metadata, waiting state, or "
            "workflow state."
        ),
    ),
    "src/sase/ace/tui/models/_loaders/_workflow_loaders.py:load_workflow_states": (
        PathPassingReview(
            exemption=(
                "Read-only FAILED-workflow enrichment: agent_meta.json is read "
                "only to locate the runner output log for the TUI fallback."
            ),
        )
    ),
    (
        "src/sase/ace/tui/models/_loaders/_workflow_loaders.py:"
        "_has_monitored_done_marker"
    ): PathPassingReview(
        exemption=(
            "Read-only settled-monitor check: done.json is inspected only to "
            "test whether its outcome is 'monitored' so the workflow-state "
            "projection can skip the vestigial launch-scaffolding row."
        ),
    ),
    "src/sase/axe/chop_lifecycle.py:_agent_completion": PathPassingReview(
        exemption=(
            "Read-only chop action finalization: done.json is inspected only "
            "to classify the terminal outcome of a registry-linked agent."
        ),
    ),
    "src/sase/history/chat_fork.py:_format_clan_member": PathPassingReview(
        exemption=(
            "Read-only clan fork context assembly: agent_meta.json and done.json "
            "are inspected only to report member model and outcome metadata."
        ),
    ),
    "src/sase/history/chat_fork.py:_format_family_member": PathPassingReview(
        exemption=(
            "Read-only family fork context assembly: agent_meta.json and done.json "
            "are inspected only to report member model and outcome metadata."
        ),
    ),
    "src/sase/agent/names/_lookup_groups.py:_iter_clan_members": PathPassingReview(
        exemption=(
            "Read-only clan completion lookup: done.json presence and outcome are "
            "inspected before consulting an exact dismissed-archive fallback."
        ),
    ),
    "src/sase/agent/names/_lookup_groups.py:_iter_family_members": PathPassingReview(
        exemption=(
            "Read-only family completion lookup: done.json presence and outcome are "
            "inspected before consulting an exact dismissed-archive fallback."
        ),
    ),
    "src/sase/core/wait_dependency_resolution/_index.py:add_many": PathPassingReview(
        exemption=(
            "Read-only dependency-index construction: done.json is batched into "
            "terminal projections without mutating artifact markers."
        ),
    ),
    "src/sase/monitor/start.py:_read_meta": PathPassingReview(
        exemption=(
            "Read-only monitor-start helper: agent_meta.json is read only to "
            "recover the lane's newest member metadata (or, on teardown, the "
            "half-created monitor member's own metadata) before any mutation "
            "goes through write_agent_meta_atomic separately."
        ),
    ),
    "src/sase/monitor/supervise.py:_read_meta": PathPassingReview(
        exemption=(
            "Read-only supervisor bootstrap: agent_meta.json is read only to "
            "recover the monitored command's configuration before running it; "
            "the terminal marker write goes through write_agent_meta_atomic "
            "separately."
        ),
    ),
}


def test_tracked_marker_path_passing_sites_are_reviewed() -> None:
    assert _path_passing_contexts() == set(_REVIEWED_PATH_PASSING_CONTEXTS)


def test_reviewed_path_passing_sites_declare_coverage() -> None:
    for context, review in _REVIEWED_PATH_PASSING_CONTEXTS.items():
        kinds = sum(bool(v) for v in (review.lifecycle_coverage, review.exemption))
        assert kinds == 1, context
