"""Audit tracked marker paths passed to non-safe callees."""

from __future__ import annotations

from tests._agent_artifact_marker_audit_helpers import (
    PathPassingReview,
    _path_passing_contexts,
)

_REVIEWED_PATH_PASSING_CONTEXTS: dict[str, PathPassingReview] = {
    "src/sase/agent/_family_promotion.py:promote_agent_to_family": PathPassingReview(
        lifecycle_coverage=(
            "Atomically rewrites agent_meta.json and immediately refreshes the "
            "Tier 1 artifact index for the same artifacts directory."
        ),
    ),
    "src/sase/axe/run_agent_wait.py:_remove_waiting_marker": PathPassingReview(
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
    "src/sase/axe/chop_lifecycle.py:_agent_completion": PathPassingReview(
        exemption=(
            "Read-only chop action finalization: done.json is inspected only "
            "to classify the terminal outcome of a registry-linked agent."
        ),
    ),
    "src/sase/history/chat.py:_format_clan_member": PathPassingReview(
        exemption=(
            "Read-only clan fork context assembly: agent_meta.json and done.json "
            "are inspected only to report member model and outcome metadata."
        ),
    ),
}


def test_tracked_marker_path_passing_sites_are_reviewed() -> None:
    assert _path_passing_contexts() == set(_REVIEWED_PATH_PASSING_CONTEXTS)


def test_reviewed_path_passing_sites_declare_coverage() -> None:
    for context, review in _REVIEWED_PATH_PASSING_CONTEXTS.items():
        kinds = sum(bool(v) for v in (review.lifecycle_coverage, review.exemption))
        assert kinds == 1, context
