"""Replay-and-evidence regression tests for bob-cli-df.2.1.4.2.

Covers the three bounded IO/publication gaps: shallow history honesty,
immutable quarantine reuse across the durability transition, and
operation/digest path plus project validation in the quarantine namespace.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_collision import candidate_from_event
from sase.sdd._artifact_link_event_history import attach_collision_history
from sase.sdd._artifact_link_event_quarantine import (
    load_artifact_link_quarantine_records,
    persist_artifact_link_quarantine_record,
)
from sase.sdd._artifact_link_event_store import reduce_artifact_link_event_inputs
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_event_store_test_helpers import (
    PROJECT_KEY,
    edge_event,
    make_store,
    write_event,
)
from tests.sdd._artifact_link_store_helpers import allow_machine_sidecar_writes


def _digest(event: dict[str, object]) -> str:
    return str(require_rust_binding("artifact_link_event_digest")(event))


def _canonical_json(event: dict[str, object]) -> str:
    return str(require_rust_binding("artifact_link_event_canonical_json")(event))


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout


def _init_repo(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def _commit_all(root: Path, message: str, when: str | None = None) -> None:
    env = None
    if when is not None:
        import os

        env = dict(os.environ)
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    _git(root, "add", "-A", env=env)
    _git(root, "commit", "-qm", message, env=env)


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
    return first, second


def test_shallow_history_marks_evidence_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    full = tmp_path / "full"
    full.mkdir()
    _init_repo(full, monkeypatch)
    event_file = full / "link-events" / "v1" / "00" / "aaa.json"
    event_file.parent.mkdir(parents=True, exist_ok=True)
    event_file.write_text('{"first":true}\n', encoding="utf-8")
    _commit_all(full, "first add")
    (full / "unrelated.txt").write_text("bump\n", encoding="utf-8")
    _commit_all(full, "unrelated second")

    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{full}", str(shallow)],
        check=True,
    )
    _git(shallow, "config", "user.name", "SASE Tests")
    _git(shallow, "config", "user.email", "sase@example.test")

    assert _git(shallow, "rev-parse", "--is-shallow-repository").strip() == "true"

    event = edge_event("a" * 32)
    digest = _digest(event)
    candidate = candidate_from_event(
        event,
        tier="durable",
        root=str(shallow),
        relative_path="link-events/v1/00/aaa.json",
        digest=digest,
    )
    (updated,) = attach_collision_history((candidate,), collided_digests={digest})
    assert updated.evidence.history_complete is False
    assert updated.evidence.first_commit_id is None
    assert updated.evidence.first_commit_at is None


def test_timezone_histories_order_by_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    plans = tmp_path / "plans"
    _init_repo(plans, monkeypatch)
    # Earlier instant 10:00Z spelled with +02:00 sorts lexically after 10:30Z.
    early = edge_event(
        "b" * 32,
        target="plan:202608/early.md",
        description="earlier instant",
    )
    late = edge_event(
        "b" * 32,
        target="plan:202608/late.md",
        description="later instant",
    )
    early_path = write_event(plans, early)
    _commit_all(plans, "early payload", when="2026-10-27T12:00:00+02:00")
    late_path = write_event(plans, late)
    _commit_all(plans, "late payload", when="2026-10-27T10:30:00+00:00")

    early_commit = (
        _git(
            plans,
            "log",
            "--diff-filter=A",
            "--format=%H",
            "--",
            early_path.relative_to(plans).as_posix(),
        )
        .splitlines()[-1]
        .strip()
    )
    late_commit = (
        _git(
            plans,
            "log",
            "--diff-filter=A",
            "--format=%H",
            "--",
            late_path.relative_to(plans).as_posix(),
        )
        .splitlines()[-1]
        .strip()
    )
    assert early_commit != late_commit

    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert len(snapshot.accepted_events) == 1
    accepted = snapshot.accepted_events[0]
    assert accepted["kind"]["edge"]["target_ref"] == "plan:202608/early.md"
    assert len(snapshot.quarantine_findings) == 1


def test_quarantine_reuse_preserves_bytes_across_basis_change(
    tmp_path: Path,
) -> None:
    first, second = _colliding_pair()
    snapshot = reduce_artifact_link_event_inputs(
        durable_events=(first, second),
        strict=True,
    )
    finding = snapshot.quarantine_findings[0]
    relative = persist_artifact_link_quarantine_record(
        tmp_path,
        finding,
        rejected_canonical_json=_canonical_json(finding.rejected_event),
    )
    before = (tmp_path / relative).read_bytes()

    stronger = replace(
        finding,
        basis="durable_beats_pending",
        detail="winner is durable; replay arrived pending",
        ambiguity=(),
        source_locator="pending:outbox:aaa",
    )
    again = persist_artifact_link_quarantine_record(
        tmp_path,
        stronger,
        rejected_canonical_json=_canonical_json(finding.rejected_event),
    )
    assert again == relative
    assert (tmp_path / relative).read_bytes() == before


def test_quarantine_reject_different_payload_is_corruption(
    tmp_path: Path,
) -> None:
    from sase.sdd._artifact_link_event_install import ArtifactLinkEventCorruptionError

    first, second = _colliding_pair()
    snapshot = reduce_artifact_link_event_inputs(
        durable_events=(first, second),
        strict=True,
    )
    finding = snapshot.quarantine_findings[0]
    persist_artifact_link_quarantine_record(
        tmp_path,
        finding,
        rejected_canonical_json=_canonical_json(finding.rejected_event),
    )
    other = edge_event(
        "a" * 32,
        target="plan:202608/other.md",
        description="different payload",
    )
    tampered = replace(finding, rejected_event=other)
    with pytest.raises(ArtifactLinkEventCorruptionError):
        persist_artifact_link_quarantine_record(
            tmp_path,
            tampered,
            rejected_canonical_json=_canonical_json(other),
        )


def test_quarantine_wrong_path_and_wrong_project_are_blocking(
    tmp_path: Path,
) -> None:
    first, second = _colliding_pair()
    snapshot = reduce_artifact_link_event_inputs(
        durable_events=(first, second),
        strict=True,
    )
    finding = snapshot.quarantine_findings[0]
    relative = persist_artifact_link_quarantine_record(
        tmp_path,
        finding,
        rejected_canonical_json=_canonical_json(finding.rejected_event),
    )
    record_path = tmp_path / relative
    payload = json.loads(record_path.read_text(encoding="utf-8"))

    wrong_path = (
        tmp_path
        / "link-events"
        / "quarantine"
        / "v1"
        / ("f" * 32)
        / f"{finding.rejected_digest}.json"
    )
    wrong_path.parent.mkdir(parents=True, exist_ok=True)
    wrong_path.write_text(json.dumps(payload), encoding="utf-8")
    record_path.unlink()

    findings, errors = load_artifact_link_quarantine_records((tmp_path,))
    assert findings == ()
    assert any("does not match" in error for error in errors)

    wrong_path.unlink()
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(payload), encoding="utf-8")
    findings, errors = load_artifact_link_quarantine_records(
        (tmp_path,), expected_project_key=PROJECT_KEY
    )
    assert errors == ()
    assert len(findings) == 1

    findings, errors = load_artifact_link_quarantine_records(
        (tmp_path,), expected_project_key="gh_other__proj"
    )
    assert findings == ()
    assert any("project" in error for error in errors)


def test_same_batch_collision_settles_idempotently_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    from sase.sdd.artifact_link_event_publisher import publish_artifact_link_events

    plans = tmp_path / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    _init_repo(plans, monkeypatch)
    (plans / "202609" / "a.md").parent.mkdir(parents=True, exist_ok=True)
    (plans / "202609" / "a.md").write_text("# Doc\n", encoding="utf-8")
    _commit_all(plans, "initial doc")

    store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": plans},
    )
    first, second = _colliding_pair()
    unrelated = edge_event(
        "b" * 32,
        target="plan:202608/fresh.md",
        description="unrelated append",
    )
    report = publish_artifact_link_events(
        store,
        (first, second, unrelated),
        push_after_commit=False,
        mutation_origin="machine",
    )
    # Same-batch collision elects one winner by digest tie-break and publishes
    # it alongside the unrelated event; the loser is quarantined. Both a*32
    # inputs share one operation id, so the published ids are (a, b) in input
    # order regardless of which a payload wins.
    assert report.published_operation_ids == ("a" * 32, "b" * 32)
    assert len(report.quarantined_event_keys) == 1
    assert len(report.quarantine_paths) == 1
    [record_path] = report.quarantine_paths
    before = record_path.read_bytes()

    loser_digest = report.quarantined_event_keys[0][1]
    loser = second if _digest(second) == loser_digest else first
    retry = publish_artifact_link_events(
        store,
        (loser,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert retry.quarantined_event_keys == (("a" * 32, loser_digest),)
    assert retry.quarantine_paths
    assert retry.quarantine_paths[0].read_bytes() == before

    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert snapshot.healthy is True
    assert len(snapshot.quarantine_findings) == 1
    records = list((plans / "link-events" / "quarantine").rglob("*.json"))
    assert len(records) == 1
    assert records[0].read_bytes() == before
