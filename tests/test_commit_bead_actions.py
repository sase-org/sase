"""Tests for commit_bead_actions extracted beside the submission loader."""

from __future__ import annotations

from sase.finalizers.declaration_manifest import commit_bead_actions


def _payloads(*actions: str) -> dict[str, object]:
    repositories = [
        {
            "repo_id": "sase",
            "action": "commit",
            "message": "feat(scope): describe the completed work",
            "bead_action": action,
        }
        for action in actions
    ]
    return {"payloads": [{"payload": {"repositories": repositories}}]}


def test_commit_bead_actions_reads_a_plain_declaration() -> None:
    has_commit, actions = commit_bead_actions(_payloads("keep"))
    assert has_commit is True
    assert actions == ["keep"]


def test_commit_bead_actions_reads_a_submission_envelope() -> None:
    envelope = {"submission": _payloads("close")}
    has_commit, actions = commit_bead_actions(envelope)
    assert has_commit is True
    assert actions == ["close"]


def test_commit_bead_actions_reads_a_prepare_wrapper() -> None:
    wrapper = {"declaration": _payloads("keep"), "verification": {"command": ["just"]}}
    has_commit, actions = commit_bead_actions(wrapper)
    assert has_commit is True
    assert actions == ["keep"]


def test_commit_bead_actions_records_close_and_keep_in_order() -> None:
    has_commit, actions = commit_bead_actions(_payloads("keep", "close"))
    assert has_commit is True
    assert actions == ["keep", "close"]


def test_commit_bead_actions_empty_without_payloads() -> None:
    assert commit_bead_actions(None) == (False, [])
    assert commit_bead_actions({}) == (False, [])
    assert commit_bead_actions({"payloads": "nope"}) == (False, [])
