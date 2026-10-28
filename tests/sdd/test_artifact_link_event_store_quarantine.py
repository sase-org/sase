"""Store-level artifact-link collision quarantine tests."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.artifact_cli._link_health_signals import event_health_values
from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_canonical import (
    canonical_artifact_link_event_object,
)
from sase.sdd._artifact_link_event_local_store import (
    artifact_link_local_event_root,
    install_local_artifact_link_event,
)
from sase.sdd.artifact_link_outbox import append_artifact_link_outbox_event
from tests.sdd._artifact_link_event_store_test_helpers import (
    PROJECT_KEY,
    edge_event,
    make_store,
    row as make_row,
    write_event,
)


def _digest(event: dict[str, object]) -> str:
    return str(require_rust_binding("artifact_link_event_digest")(event))


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_repo(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "GIT_AUTHOR_EMAIL": "sase@example.test",
        "GIT_AUTHOR_NAME": "SASE Tests",
        "GIT_COMMITTER_EMAIL": "sase@example.test",
        "GIT_COMMITTER_NAME": "SASE Tests",
    }.items():
        monkeypatch.setenv(key, value)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "SASE Tests")
    _git(root, "config", "user.email", "sase@example.test")
    _git(root, "config", "commit.gpgsign", "false")


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)


def _colliding_pair() -> tuple[dict[str, object], dict[str, object]]:
    created_at = "2026-09-09T12:00:00Z"
    first = edge_event(
        "a" * 32,
        target="plan:202608/original.md",
        description="original payload",
        created_at=created_at,
    )
    second = edge_event(
        "a" * 32,
        target="plan:202608/replay.md",
        description="replay payload",
        created_at=created_at,
    )
    if _digest(first) > _digest(second):
        return first, second
    return second, first


def test_historical_original_wins_with_identical_timestamps_and_reversed_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path, monkeypatch)
    plans = tmp_path / "plans"
    _init_git_repo(plans, monkeypatch)
    original, replay = _colliding_pair()
    assert _digest(original) > _digest(replay)

    original_path = write_event(plans, original)
    _commit(plans, "original durable event")
    replay_path = write_event(plans, replay)
    _commit(plans, "conflicting replay")
    before = _git(plans, "status", "--porcelain").stdout

    snapshot = store.artifact_link_event_snapshot(strict=True)

    assert original_path.is_file()
    assert replay_path.is_file()
    assert original_path.read_text(encoding="utf-8")
    assert replay_path.read_text(encoding="utf-8")
    assert snapshot.durable_event_count == 2
    assert len(snapshot.accepted_events) == 1
    accepted = snapshot.accepted_events[0]
    assert (
        accepted["kind"]["edge"]["target_ref"] == original["kind"]["edge"]["target_ref"]
    )
    assert len(snapshot.quarantine_findings) == 1
    finding = snapshot.quarantine_findings[0]
    assert finding.basis == "historical_ancestor_wins"
    assert finding.rejected_digest == _digest(replay)
    assert finding.accepted_digest == _digest(original)
    assert snapshot.healthy is True
    assert _git(plans, "status", "--porcelain").stdout == before
    quarantine_root = plans / "link-events" / "quarantine"
    assert list(quarantine_root.rglob("*.json")) == []

    unrelated = edge_event(
        "b" * 32,
        target="plan:202608/fresh.md",
        description="unrelated append",
    )
    write_event(plans, unrelated)
    _commit(plans, "unrelated event")
    later = store.artifact_link_event_snapshot(strict=True)
    targets = {
        row["target_ref"]
        for row in later.rows
        if isinstance(row.get("target_ref"), str)
    }
    assert original["kind"]["edge"]["target_ref"] in targets
    assert unrelated["kind"]["edge"]["target_ref"] in targets
    assert replay["kind"]["edge"]["target_ref"] not in targets
    store.upsert_row(
        make_row(
            source="plan:202609/fresh.md",
            relation="related",
            target="plan:202609/other.md",
            description="unrelated legacy write",
        )
    )


def test_pending_replay_does_not_override_durable_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path, monkeypatch)
    original, replay = _colliding_pair()
    write_event(tmp_path / "plans", original)
    append_artifact_link_outbox_event(
        project_key=PROJECT_KEY,
        agent_name="agent:pending.athena.worker",
        run_id="run-1",
        event=replay,
    )

    snapshot = store.artifact_link_event_snapshot(strict=True)

    assert snapshot.durable_event_count == 1
    assert snapshot.pending_event_count == 1
    assert snapshot.pending_rows == ()
    assert len(snapshot.accepted_events) == 1
    assert (
        snapshot.accepted_events[0]["kind"]["edge"]["target_ref"]
        == (original["kind"]["edge"]["target_ref"])
    )
    assert snapshot.quarantine_findings[0].basis == "durable_beats_pending"


def test_covers_row_keeps_rejected_edge_from_resurrecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path, monkeypatch)
    original, replay = _colliding_pair()
    write_event(tmp_path / "plans", original)
    write_event(tmp_path / "plans", replay)

    snapshot = store.artifact_link_event_snapshot(strict=True)
    rejected = snapshot.quarantine_findings[0].rejected_event
    rejected_edge = rejected["kind"]["edge"]
    stale = make_row(
        source=str(rejected_edge["source_ref"]),
        relation=str(rejected_edge["relation"]),
        target=str(rejected_edge["target_ref"]),
        description="stale legacy row for quarantined edge",
    )
    unrelated = make_row(
        source="plan:202609/unrelated.md",
        relation="related",
        target="plan:202609/other.md",
    )

    assert snapshot.covers_row(stale) is True
    assert snapshot.covers_row(unrelated) is False
    assert snapshot.covers_row(snapshot.rows[0]) is True


def test_malformed_event_object_still_blocks_the_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path, monkeypatch)
    original, replay = _colliding_pair()
    write_event(tmp_path / "plans", original)
    write_event(tmp_path / "plans", replay)
    bad = tmp_path / "plans" / "link-events" / "v1" / "00" / "dead.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not json", encoding="utf-8")

    snapshot = store.artifact_link_event_snapshot(strict=False)

    assert snapshot.validation_findings
    assert snapshot.healthy is False
    with pytest.raises(RuntimeError, match="invalid"):
        store.artifact_link_event_snapshot(strict=True)


def test_local_admission_sequence_picks_the_first_installed_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path, monkeypatch)
    first, second = _colliding_pair()
    first_obj = canonical_artifact_link_event_object(first)
    second_obj = canonical_artifact_link_event_object(second)
    assert install_local_artifact_link_event(PROJECT_KEY, first_obj)
    assert install_local_artifact_link_event(PROJECT_KEY, second_obj)

    snapshot = store.artifact_link_event_snapshot(strict=True)
    local_root = artifact_link_local_event_root(PROJECT_KEY)

    assert (local_root / first_obj.relative_path).is_file()
    assert (local_root / second_obj.relative_path).is_file()
    assert (
        snapshot.accepted_events[0]["kind"]["edge"]["target_ref"]
        == (first["kind"]["edge"]["target_ref"])
    )
    assert snapshot.quarantine_findings[0].basis == "admission_sequence_wins"
    assert snapshot.quarantine_findings[0].rejected_digest == second_obj.digest


def test_digest_tie_break_without_history_keeps_the_store_writable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path, monkeypatch)
    first, second = _colliding_pair()
    write_event(tmp_path / "plans", first)
    write_event(tmp_path / "plans", second)

    snapshot = store.artifact_link_event_snapshot(strict=True)
    expected = first if _digest(first) < _digest(second) else second

    assert snapshot.quarantine_findings[0].basis == "digest_tie_break_unordered"
    assert (
        snapshot.accepted_events[0]["kind"]["edge"]["target_ref"]
        == (expected["kind"]["edge"]["target_ref"])
    )
    assert snapshot.healthy is True
    health = event_health_values(store)
    assert health.event_quarantine_findings
    assert "collision" in health.event_quarantine_findings[0]
