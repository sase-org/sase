"""Regression tests for reconciling and replaying bead event streams."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.project import BeadProject
from sase.bead.sync_worker import run_managed_sync_worker
from sase.sdd._commit_store import push_sdd_store_after_commit
from sase.sdd.store import SddStore

from .sync_conflict_regression_helpers import (
    _assert_store_matches_fresh_reduction,
    _bead_artifact_bytes,
    _build_replay_histories,
    _clone,
    _commit,
    _event_records_by_id,
    _git,
    _log_records,
    _opposite_direction_workspace,
    _seed_replay_divergence,
    _seed_same_stream_remote,
)


def test_generic_sdd_push_reconciles_same_stream_and_derived_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote, left, right, epic_id, first_id, second_id = _seed_same_stream_remote(
        tmp_path
    )
    with BeadProject(left, beads_dirname="beads") as project:
        project.update(first_id, title="First from left")
    _commit(left, "left same-stream append", "beads")
    with BeadProject(right, beads_dirname="beads") as project:
        project.update(second_id, title="Second from right")
    _commit(right, "right same-stream append", "beads")
    _git(right, "push")

    log_path = tmp_path / "generic-sdd-sync.log"
    monkeypatch.setattr(
        "sase.bead.sync._new_sync_log_path",
        lambda: log_path,
    )
    store = SddStore(
        storage="separate_repo",
        sdd_dir=left,
        repo_root=left,
        remote_url=str(remote),
    )

    push_sdd_store_after_commit(store, push_after_commit=True)

    assert _git(left, "status", "--porcelain").stdout == ""
    assert not (left / ".git/rebase-merge").exists()
    assert not (left / ".git/rebase-apply").exists()
    assert _git(left, "diff", "--name-only", "--diff-filter=U").stdout == ""
    stream_path = left / f"beads/events/streams/{epic_id}.jsonl"
    assert len(stream_path.read_text(encoding="utf-8").splitlines()) == 5
    projection = [
        json.loads(line)
        for line in (left / "beads/issues.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(projection) == 3
    assert len({row["id"] for row in projection}) == 3
    assert (
        json.loads((left / "beads/events/manifest.json").read_text(encoding="utf-8"))[
            "stream_count"
        ]
        == 1
    )

    verify = tmp_path / "verify-same-stream"
    _clone(remote, verify)
    with BeadProject(verify, beads_dirname="beads") as project:
        assert project.show(first_id).title == "First from left"
        assert project.show(second_id).title == "Second from right"

    records = _log_records(log_path)
    resolution = next(
        record for record in records if record["event"] == "conflict_resolution"
    )
    assert set(resolution["resolved_files"]) == {
        f"beads/events/streams/{epic_id}.jsonl",
        "beads/events/manifest.json",
        "beads/issues.jsonl",
    }
    integration = next(record for record in records if record["event"] == "integration")
    assert set(integration["resolved_files"]) == set(resolution["resolved_files"])


def test_managed_sync_worker_replays_deep_multi_commit_divergence(
    tmp_path: Path,
) -> None:
    remote, local, upstream, contested_ids, quiet_id = _seed_replay_divergence(tmp_path)
    _build_replay_histories(local, upstream, contested_ids)
    expected_events = _event_records_by_id(local)
    for event_id, event in _event_records_by_id(upstream).items():
        assert event_id not in expected_events or expected_events[event_id] == event
        expected_events[event_id] = event
    quiet_path = local / f"beads/events/streams/{quiet_id}.jsonl"
    quiet_bytes = quiet_path.read_bytes()
    assert b"Qui\xc3\xa9t" in quiet_bytes
    _git(upstream, "push")

    log_path = tmp_path / "deep-replay.log"
    outcome = run_managed_sync_worker(
        local,
        local / "beads",
        log_path=log_path,
    )

    assert outcome.pushed is True
    assert outcome.integrated is True
    assert outcome.error is None
    assert _git(local, "status", "--porcelain").stdout == ""
    assert not (local / ".git/rebase-merge").exists()
    assert not (local / ".git/rebase-apply").exists()
    assert _git(local, "diff", "--name-only", "--diff-filter=U").stdout == ""
    assert _event_records_by_id(local) == expected_events
    assert quiet_path.read_bytes() == quiet_bytes
    _assert_store_matches_fresh_reduction(local)

    with BeadProject(local, beads_dirname="beads") as project:
        first = project.show(contested_ids[0])
        second = project.show(contested_ids[1])
    assert first.title == "First from local commit one"
    assert first.notes.endswith("First from upstream")
    assert first.description == "First from local commit three"
    assert second.notes.endswith("Second from local commit two")
    assert second.description == "Second from upstream"
    assert second.design == "Second from local commit four"

    verify = tmp_path / "deep-replay-verify"
    _clone(remote, verify)
    assert _bead_artifact_bytes(verify) == _bead_artifact_bytes(local)
    records = _log_records(log_path)
    assert sum(record["event"] == "conflict_resolution" for record in records) >= 3
    assert records[-1]["event"] == "completed"


def test_managed_sync_worker_converges_in_opposite_replay_directions(
    tmp_path: Path,
) -> None:
    _remote, local, upstream, contested_ids, _quiet_id = _seed_replay_divergence(
        tmp_path
    )
    _build_replay_histories(local, upstream, contested_ids)
    _right_remote, local_over_upstream = _opposite_direction_workspace(
        tmp_path,
        name="local-over-upstream",
        upstream_repo=upstream,
        local_repo=local,
    )
    _left_remote, upstream_over_local = _opposite_direction_workspace(
        tmp_path,
        name="upstream-over-local",
        upstream_repo=local,
        local_repo=upstream,
    )

    local_outcome = run_managed_sync_worker(
        local_over_upstream,
        local_over_upstream / "beads",
        log_path=tmp_path / "local-over-upstream.log",
    )
    upstream_outcome = run_managed_sync_worker(
        upstream_over_local,
        upstream_over_local / "beads",
        log_path=tmp_path / "upstream-over-local.log",
    )

    assert local_outcome.pushed is True
    assert local_outcome.integrated is True
    assert upstream_outcome.pushed is True
    assert upstream_outcome.integrated is True
    assert _bead_artifact_bytes(local_over_upstream) == _bead_artifact_bytes(
        upstream_over_local
    )
    _assert_store_matches_fresh_reduction(local_over_upstream)
    _assert_store_matches_fresh_reduction(upstream_over_local)
