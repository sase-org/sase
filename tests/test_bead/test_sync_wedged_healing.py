"""Bead sync rollback and wedged-clone healing (bead-sync phase).

Real-git coverage for the bead-sync work: the Python stream-integrity guard
tolerates pure-reorder streams written by the old timestamp-sorting merge, the
managed sync worker publishes across non-monotonic upstream timestamps, a
wedged clone heals and publishes, a rejected post-integration guard restores
the starting HEAD with a recovery ref, and a deadline timeout mid-rebase
leaves the clone restored.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sase.bead._stream_integrity import BeadStreamIntegrityError
from sase.bead._stream_integrity_analysis import analyze_stream_against_ancestor
from sase.bead._stream_integrity_files import (
    encode_stream_events,
    parse_stream_text,
)
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.bead.sync_worker import run_managed_sync_worker
from sase.sdd._git import SddGitCommandTimeout

from .sync_conflict_regression_helpers import _clone, _commit, _git
from .sync_test_helpers import init_git_repo


def _event(event_id: str, **fields: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_id": event_id,
        "timestamp": "2026-08-13T00:00:00Z",
        "actor": "tester@example.com",
        "operation": "issue_updated",
        "note": event_id,
    }
    payload.update(fields)
    return payload


def _analyze(ancestor: list[dict[str, object]], local: list[dict[str, object]]) -> str:
    return analyze_stream_against_ancestor(
        ancestor,
        local,
        ancestor_text=encode_stream_events(ancestor),
        other_streams={},
        new_stream_ids=set(),
        stream_id="sase-l1",
    ).kind


def test_analyze_pure_reorder_is_not_a_shrink() -> None:
    ancestor = [_event("a"), _event("b"), _event("c")]
    assert _analyze(ancestor, [_event("b"), _event("c"), _event("a")]) == "ok"
    assert (
        _analyze(ancestor, [_event("c"), _event("b"), _event("a"), _event("d")]) == "ok"
    )


def test_analyze_still_refuses_missing_and_rewrite() -> None:
    ancestor = [_event("a"), _event("b"), _event("c")]
    assert _analyze(ancestor, ancestor[:2]) == "restore_exact"
    assert _analyze(ancestor, [_event("b"), _event("a")]) == "restore_superset"
    rewritten = [_event("a"), _event("b", note="mutated"), _event("c")]
    assert _analyze(ancestor, rewritten) == "rewrite"


def _seed_remote(tmp_path: Path) -> tuple[Path, Path, str]:
    """Seed a bare remote plus one clone with a three-event bead stream."""
    remote = tmp_path / "remote.git"
    import subprocess

    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / "seed"
    seed.mkdir()
    init_git_repo(seed)
    _git(seed, "branch", "-M", "main")
    (seed / ".gitignore").write_text("beads.db*\n", encoding="utf-8")
    with BeadProject.init(seed, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create("Healing stream", IssueType.PLAN)
        project.update(issue.id, notes="second event")
        project.update(issue.id, notes="third event")
    _commit(seed, "seed append-only stream")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    return remote, seed, issue.id


def _stream_events(repo: Path, issue_id: str) -> list[dict[str, object]]:
    text = (repo / f"events/streams/{issue_id}.jsonl").read_text(encoding="utf-8")
    return parse_stream_text(text)


def _write_stream(repo: Path, issue_id: str, events: list[dict[str, object]]) -> None:
    path = repo / f"events/streams/{issue_id}.jsonl"
    path.write_text(encode_stream_events(events), encoding="utf-8")


def _append_crafted(
    events: list[dict[str, object]], event_id: str, timestamp: str
) -> dict[str, object]:
    appended = copy.deepcopy(events[-1])
    assert isinstance(appended, dict)
    appended["event_id"] = event_id
    appended["timestamp"] = timestamp
    return appended


def _rev_parse(repo: Path, rev: str = "HEAD") -> str:
    return _git(repo, "rev-parse", rev).stdout.strip()


def _recovery_refs(repo: Path) -> list[str]:
    result = _git(
        repo, "for-each-ref", "--format=%(refname)", "refs/sase/recovery/", check=False
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _rebase_markers_present(repo: Path) -> bool:
    git_dir = _git(repo, "rev-parse", "--git-dir").stdout.strip()
    root = repo / git_dir if not Path(git_dir).is_absolute() else Path(git_dir)
    return (root / "rebase-merge").exists() or (root / "rebase-apply").exists()


def test_sync_publishes_non_monotonic_upstream_with_local_note(
    tmp_path: Path,
) -> None:
    remote, _seed, issue_id = _seed_remote(tmp_path)
    # Clone before the upstream push so the local side must integrate it.
    local = tmp_path / "local"
    _clone(remote, local)
    upstream = tmp_path / "upstream"
    _clone(remote, upstream)
    base = _stream_events(upstream, issue_id)
    assert len(base) >= 3
    late = _append_crafted(base, f"{issue_id}-late", "2026-09-02T13:55:00Z")
    early = _append_crafted(base, f"{issue_id}-early", "2026-09-02T13:13:00Z")
    early2 = _append_crafted(base, f"{issue_id}-early2", "2026-09-02T13:14:00Z")
    _write_stream(upstream, issue_id, [*base, late, early, early2])
    _commit(upstream, "upstream non-monotonic append")
    _git(upstream, "push")

    with BeadProject(local, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        project.update(issue_id, notes="local healing note")
    _commit(local, "local note append")

    outcome = run_managed_sync_worker(
        local,
        local,
        log_path=tmp_path / "non-monotonic.log",
    )

    assert outcome.error is None
    assert outcome.pushed is True
    merged_ids = [event["event_id"] for event in _stream_events(local, issue_id)]
    assert merged_ids.index(f"{issue_id}-late") < merged_ids.index(f"{issue_id}-early")
    assert merged_ids.index(f"{issue_id}-early") < merged_ids.index(
        f"{issue_id}-early2"
    )
    merged_text = (local / f"events/streams/{issue_id}.jsonl").read_text(
        encoding="utf-8"
    )
    assert "local healing note" in merged_text
    assert not _rebase_markers_present(local)


def test_wedged_clone_heals_and_publishes(tmp_path: Path) -> None:
    remote, _seed, issue_id = _seed_remote(tmp_path)
    local = tmp_path / "wedged"
    _clone(remote, local)
    base = _stream_events(local, issue_id)
    # Reorder only the tail, like the old timestamp-sorting merge did: the
    # creation event stays first so the stream still reduces.
    reordered = [base[0], base[2], base[1]]
    note = _append_crafted(reordered, f"{issue_id}-wedged-note", "2026-09-04T00:00:00Z")
    _write_stream(local, issue_id, [*reordered, note])
    _commit(local, "chore(beads): wedged reorder with pending note")

    outcome = run_managed_sync_worker(
        local,
        local,
        log_path=tmp_path / "wedged.log",
    )

    assert outcome.error is None
    assert outcome.pushed is True
    verify = tmp_path / "verify"
    _clone(remote, verify)
    verify_text = (verify / f"events/streams/{issue_id}.jsonl").read_text(
        encoding="utf-8"
    )
    assert f"{issue_id}-wedged-note" in verify_text


def test_forced_post_guard_failure_restores_starting_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.bead._stream_integrity as integrity_mod

    remote, _seed, issue_id = _seed_remote(tmp_path)
    # Clone before the upstream push so the sync must integrate it.
    local = tmp_path / "local"
    _clone(remote, local)
    upstream = tmp_path / "upstream"
    _clone(remote, upstream)
    with BeadProject(upstream, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        project.update(issue_id, notes="upstream append")
    _commit(upstream, "upstream append")
    _git(upstream, "push")

    with BeadProject(local, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        project.update(issue_id, notes="local append")
    _commit(local, "local append")
    starting_head = _rev_parse(local)

    real_guard = integrity_mod.refuse_unpublished_event_stream_shrink
    calls = {"count": 0}

    def flaky_guard(
        repo_root: Path, beads_dir: Path, *, ignore_unreadable: bool = False
    ) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            return real_guard(repo_root, beads_dir, ignore_unreadable=ignore_unreadable)
        raise BeadStreamIntegrityError("forced post-guard shrink for rollback test")

    monkeypatch.setattr(
        integrity_mod, "refuse_unpublished_event_stream_shrink", flaky_guard
    )

    log_path = tmp_path / "rollback.log"
    outcome = run_managed_sync_worker(local, local, log_path=log_path)

    assert outcome.pushed is False
    assert outcome.error is not None
    assert "forced post-guard shrink" in outcome.error
    assert calls["count"] == 2
    assert _rev_parse(local) == starting_head
    assert not _rebase_markers_present(local)
    assert _recovery_refs(local), "rejected HEAD must keep a recovery ref"
    records = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    rollbacks = [r for r in records if r.get("event") == "post_guard_rollback"]
    assert rollbacks
    assert "restored pre-integration HEAD" in rollbacks[-1].get("summary", "")


def test_deadline_timeout_mid_rebase_restores_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.bead.sync_worker as worker_mod

    remote, _seed, issue_id = _seed_remote(tmp_path)
    # Clone before the upstream push so the sync must rebase onto it.
    local = tmp_path / "local"
    _clone(remote, local)
    upstream = tmp_path / "upstream"
    _clone(remote, upstream)
    with BeadProject(upstream, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        project.update(issue_id, notes="upstream append")
    _commit(upstream, "upstream append")
    _git(upstream, "push")

    with BeadProject(local, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        project.update(issue_id, notes="local append")
    _commit(local, "local append")
    starting_head = _rev_parse(local)

    real_factory = worker_mod._git_runner_for_deadline

    def timeout_factory(deadline: float | None):  # type: ignore[no-untyped-def]
        real = real_factory(deadline)

        def fake(repo_root, args, *, op, network=False):  # type: ignore[no-untyped-def]
            if op == "bead.sync.rebase":
                real(repo_root, args, op=op, network=network)
                raise SddGitCommandTimeout("test timeout right after rebase")
            return real(repo_root, args, op=op, network=network)

        return fake

    monkeypatch.setattr(worker_mod, "_git_runner_for_deadline", timeout_factory)

    outcome = run_managed_sync_worker(
        local,
        local,
        log_path=tmp_path / "timeout.log",
    )

    assert outcome.pushed is False
    assert outcome.error is not None
    assert "timed out" in outcome.error
    assert _rev_parse(local) == starting_head
    assert not _rebase_markers_present(local)
