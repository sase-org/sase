"""Full-store regression for identical copies with skewed commit clocks."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_history import attach_collision_history
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests.sdd._artifact_link_event_store_test_helpers import (
    PROJECT_KEY,
    edge_event,
    write_event,
)


def _git(root: Path, *args: str, when: str | None = None) -> str:
    env = None
    if when is not None:
        env = dict(os.environ)
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "SASE Tests")
    _git(root, "config", "user.email", "sase@example.test")
    _git(root, "config", "commit.gpgsign", "false")


def _commit(root: Path, message: str, when: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message, when=when)
    return _git(root, "rev-parse", "HEAD")


def _digest(event: dict[str, object]) -> str:
    return str(require_rust_binding("artifact_link_event_digest")(event))


def test_store_preserves_earliest_history_across_skewed_identical_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_repo = tmp_path / "shared"
    _init_repo(shared_repo)
    plans = shared_repo / "plans"
    research = shared_repo / "research"
    plans.mkdir()
    research.mkdir()

    copied_payload = edge_event(
        "a" * 32,
        target="plan:202610/copied.md",
        description="same payload in two sidecars",
        created_at="2026-10-27T09:00:00Z",
    )
    first_path = write_event(plans, copied_payload)
    first_commit = _commit(shared_repo, "first copy", "2026-10-27T12:00:00Z")
    copy_path = write_event(research, copied_payload)
    copy_commit = _commit(
        shared_repo, "descendant copy with skewed clock", "2026-10-27T10:00:00Z"
    )

    competitor_repo = tmp_path / "competitor"
    _init_repo(competitor_repo)
    competitor_payload = edge_event(
        "a" * 32,
        target="plan:202610/competitor.md",
        description="independent payload",
        created_at="2026-10-27T09:00:00Z",
    )
    competitor_path = write_event(competitor_repo, competitor_payload)
    _commit(competitor_repo, "independent competitor", "2026-10-27T11:00:00Z")
    source_bytes = {
        first_path: first_path.read_bytes(),
        copy_path: copy_path.read_bytes(),
        competitor_path: competitor_path.read_bytes(),
    }

    store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={
            "plan": plans,
            "research": research,
            "attachment": competitor_repo,
        },
    )
    snapshot = store.artifact_link_event_snapshot(strict=True)

    copied_digest = _digest(copied_payload)
    competitor_digest = _digest(competitor_payload)
    assert (
        _git(shared_repo, "merge-base", "--is-ancestor", first_commit, copy_commit)
        == ""
    )
    copied_candidates = [
        candidate
        for candidate in snapshot.candidates
        if candidate.digest == copied_digest
    ]
    assert len(copied_candidates) == 2

    # The store's public path gathers the same evidence and lets the pinned core
    # select the independent 11:00 payload over A's first 12:00 occurrence.
    evidenced = attach_collision_history(
        snapshot.candidates,
        collided_digests={copied_digest, competitor_digest},
    )
    [evidenced_copy] = [
        candidate
        for candidate in evidenced
        if candidate.digest == copied_digest and candidate.root == str(research)
    ]
    assert first_commit in evidenced_copy.evidence.ancestor_commit_ids
    assert [
        event["kind"]["edge"]["target_ref"] for event in snapshot.accepted_events
    ] == ["plan:202610/competitor.md"]
    assert len(snapshot.accepted_events) == 1
    assert len(snapshot.quarantine_findings) == 1
    assert snapshot.quarantine_findings[0].rejected_digest == copied_digest

    assert source_bytes[first_path] == source_bytes[copy_path]
    assert first_path.read_bytes() == source_bytes[first_path]
    assert copy_path.read_bytes() == source_bytes[copy_path]
    assert competitor_path.read_bytes() == source_bytes[competitor_path]
    assert _git(shared_repo, "status", "--porcelain") == ""
    assert _git(competitor_repo, "status", "--porcelain") == ""
