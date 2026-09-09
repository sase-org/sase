"""Pending commit-checkpoint recovery decision facade."""

from __future__ import annotations

from sase.core.pending_commit_checkpoint import (
    decide_pending_commit_checkpoint_recovery,
)


def test_pending_commit_checkpoint_schema_version() -> None:
    decision = decide_pending_commit_checkpoint_recovery({})
    assert decision["schema_version"] == 1
    assert decision["action"] == "none"


def test_pending_hook_checkpoint_resumes() -> None:
    decision = decide_pending_commit_checkpoint_recovery(
        {
            "checkpoint_present": True,
            "repository_matches": True,
            "subject_matches": True,
            "payload_matches": True,
            "has_operation_id": True,
            "independent_ownership_evidence": True,
            "dispatch_completed": True,
            "pending_after_hook": True,
            "commit_sha_present": True,
        }
    )
    assert decision["action"] == "resume"
    assert decision["schema_version"] == 1
    assert "pending_after_hook" in decision["diagnostics"]


def test_foreign_pending_checkpoint_fails_closed() -> None:
    decision = decide_pending_commit_checkpoint_recovery(
        {
            "checkpoint_present": True,
            "repository_matches": False,
            "subject_matches": True,
            "payload_matches": True,
            "has_operation_id": True,
            "independent_ownership_evidence": True,
            "pending_after_hook": True,
            "commit_sha_present": True,
        }
    )
    assert decision["action"] == "fail"
