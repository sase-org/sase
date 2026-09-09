"""Pending commit-checkpoint recovery decision facade."""

from __future__ import annotations

from sase.core.pending_commit_checkpoint import (
    decide_pending_commit_checkpoint_recovery,
)


def _owned_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "checkpoint_present": True,
        "repository_matches": True,
        "subject_matches": True,
        "payload_matches": True,
        "checkpoint_method": "create_commit",
        "accepted_action": "commit",
        "checkpoint_payload_identity": "fix(final): reconcile commit declaration\n\nbody",
        "accepted_payload_identity": "fix(final): reconcile commit declaration\n\nbody",
        "checkpoint_run_id": "run-1",
        "current_run_id": "run-1",
        "checkpoint_agent_id": "agent-1",
        "current_agent_id": "agent-1",
        "has_operation_id": True,
        "dispatch_completed": True,
        "pending_after_hook": True,
        "commit_sha_present": True,
    }
    request.update(overrides)
    return request


def test_pending_commit_checkpoint_schema_version() -> None:
    decision = decide_pending_commit_checkpoint_recovery({})
    assert decision["schema_version"] == 2
    assert decision["action"] == "none"


def test_pending_hook_checkpoint_resumes() -> None:
    decision = decide_pending_commit_checkpoint_recovery(_owned_request())
    assert decision["action"] == "resume"
    assert decision["schema_version"] == 2
    assert "pending_after_hook" in decision["diagnostics"]


def test_foreign_pending_checkpoint_fails_closed() -> None:
    decision = decide_pending_commit_checkpoint_recovery(
        _owned_request(repository_matches=False)
    )
    assert decision["action"] == "fail"


def test_foreign_run_fails_closed() -> None:
    decision = decide_pending_commit_checkpoint_recovery(
        _owned_request(checkpoint_run_id="run-2")
    )
    assert decision["action"] == "fail"
    assert "checkpoint_run_mismatch" in decision["diagnostics"]


def test_same_subject_different_body_fails_closed() -> None:
    decision = decide_pending_commit_checkpoint_recovery(
        _owned_request(
            checkpoint_payload_identity="fix(final): reconcile commit declaration\n\nold",
            accepted_payload_identity="fix(final): reconcile commit declaration\n\nnew",
        )
    )
    assert decision["action"] == "fail"
    assert "checkpoint_payload_mismatch" in decision["diagnostics"]
