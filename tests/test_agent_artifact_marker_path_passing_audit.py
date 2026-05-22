"""Audit tracked marker paths passed to non-safe callees."""

from __future__ import annotations

from tests._agent_artifact_marker_audit_helpers import (
    PathPassingReview,
    _path_passing_contexts,
)

_REVIEWED_PATH_PASSING_CONTEXTS: dict[str, PathPassingReview] = {}


def test_tracked_marker_path_passing_sites_are_reviewed() -> None:
    assert _path_passing_contexts() == set(_REVIEWED_PATH_PASSING_CONTEXTS)


def test_reviewed_path_passing_sites_declare_coverage() -> None:
    for context, review in _REVIEWED_PATH_PASSING_CONTEXTS.items():
        kinds = sum(bool(v) for v in (review.lifecycle_coverage, review.exemption))
        assert kinds == 1, context
