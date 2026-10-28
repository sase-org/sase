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
from sase.sdd._artifact_link_event_canonical import canonical_artifact_link_event_object
from sase.sdd._artifact_link_event_collision import candidate_from_event
from sase.sdd._artifact_link_event_history import attach_collision_history
from sase.sdd._artifact_link_event_quarantine import (
    load_artifact_link_quarantine_records,
    persist_artifact_link_quarantine_record,
)
from sase.sdd._artifact_link_event_store import reduce_artifact_link_event_inputs
from sase.sdd._artifact_link_outbox_io import read_artifact_link_outbox_entries
from sase.sdd.artifact_link_event_publisher import (
    observation_or_put_event_from_row,
    publish_artifact_link_events,
)
from sase.sdd.artifact_link_outbox import (
    append_artifact_link_outbox_event,
    drain_artifact_link_outbox,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.main.artifact_link_outbox_helpers import _init_plans_repo
from tests.sdd._artifact_link_event_store_test_helpers import (
    PROJECT_KEY,
    edge_event,
    make_store,
    row as make_row,
    write_event,
)
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes


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


def _colliding_pair(
    *, origin: str = "manual"
) -> tuple[dict[str, object], dict[str, object]]:
    created_at = "2026-09-09T12:00:00Z"
    first = edge_event(
        "a" * 32,
        target="plan:202608/original.md",
        description="original payload",
        origin=origin,
        created_at=created_at,
    )
    second = edge_event(
        "a" * 32,
        target="plan:202608/replay.md",
        description="replay payload",
        origin=origin,
        created_at=created_at,
    )
    return first, second


def _event_target(event: dict[str, object]) -> str:
    kind = event.get("kind")
    if not isinstance(kind, dict):
        raise AssertionError("event is missing kind")
    edge = kind.get("edge")
    if not isinstance(edge, dict):
        raise AssertionError("event kind is missing an edge")
    if edge.get("kind") == "undirected":
        return str(edge.get("right_ref") or "")
    return str(edge.get("target_ref") or "")


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


def test_cross_root_clone_gathers_ancestry_through_store_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    _init_repo(plans, monkeypatch)
    early = edge_event(
        "c" * 32,
        target="plan:202608/original.md",
        description="earlier payload at later clock",
    )
    late = edge_event(
        "c" * 32,
        target="plan:202608/clock-skew.md",
        description="later payload at earlier clock",
    )
    early_path = write_event(plans, early)
    _commit_all(plans, "add original A", when="2026-10-27T12:00:00Z")
    early_commit = _git(plans, "rev-parse", "HEAD").strip()

    if research.exists():
        research.rmdir()
    subprocess.run(
        ["git", "clone", "-q", f"file://{plans}", str(research)],
        check=True,
    )
    _git(research, "config", "user.name", "SASE Tests")
    _git(research, "config", "user.email", "sase@example.test")
    _git(research, "config", "commit.gpgsign", "false")
    cloned_early = research / early_path.relative_to(plans)
    cloned_early.unlink()
    late_path = write_event(research, late)
    _commit_all(research, "replace A with B", when="2026-10-27T10:00:00Z")
    late_commit = _git(research, "rev-parse", "HEAD").strip()
    assert (
        _git(research, "merge-base", "--is-ancestor", early_commit, late_commit) == ""
    )

    early_candidate = candidate_from_event(
        early,
        tier="durable",
        root=str(plans.resolve()),
        relative_path=early_path.relative_to(plans).as_posix(),
        digest=_digest(early),
    )
    late_candidate = candidate_from_event(
        late,
        tier="durable",
        root=str(research.resolve()),
        relative_path=late_path.relative_to(research).as_posix(),
        digest=_digest(late),
    )
    updated = attach_collision_history(
        (early_candidate, late_candidate),
        collided_digests={_digest(early), _digest(late)},
    )
    by_digest = {item.digest: item for item in updated}
    assert by_digest[_digest(early)].evidence.history_complete is True
    assert by_digest[_digest(late)].evidence.history_complete is True
    assert early_commit in by_digest[_digest(late)].evidence.ancestor_commit_ids
    assert by_digest[_digest(early)].evidence.ancestor_commit_ids == ()
    assert early_commit not in by_digest[_digest(early)].evidence.ancestor_commit_ids

    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert len(snapshot.accepted_events) == 1
    accepted = snapshot.accepted_events[0]
    assert accepted["kind"]["edge"]["target_ref"] == "plan:202608/original.md"
    assert snapshot.quarantine_findings[0].basis == "historical_ancestor_wins"


def test_independent_root_timezone_histories_order_by_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    _init_repo(plans, monkeypatch)
    _init_repo(research, monkeypatch)
    early = edge_event(
        "d" * 32,
        target="plan:202608/early.md",
        description="earlier instant in independent root",
    )
    late = edge_event(
        "d" * 32,
        target="research:202608/late.md",
        source="research:202608/src.md",
        description="later instant in independent root",
    )
    write_event(plans, early)
    _commit_all(plans, "early independent", when="2026-10-27T12:00:00+02:00")
    write_event(research, late)
    _commit_all(research, "late independent", when="2026-10-27T10:30:00+00:00")

    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert len(snapshot.accepted_events) == 1
    accepted = snapshot.accepted_events[0]
    assert accepted["kind"]["edge"]["target_ref"] == "plan:202608/early.md"
    assert snapshot.quarantine_findings[0].rejected_digest == _digest(late)


def test_duplicate_independent_roots_do_not_invent_ancestry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    _init_repo(plans, monkeypatch)
    _init_repo(research, monkeypatch)
    payload = edge_event(
        "e" * 32,
        target="plan:202608/copied.md",
        description="identical payload in two roots",
    )
    competitor = edge_event(
        "e" * 32,
        target="plan:202608/competitor.md",
        description="competing payload",
    )
    first_path = write_event(plans, payload)
    _commit_all(plans, "plans copy")
    second_path = write_event(research, payload)
    _commit_all(research, "research copy")
    write_event(plans, competitor)
    _commit_all(plans, "competitor")

    plans_candidate = candidate_from_event(
        payload,
        tier="durable",
        root=str(plans.resolve()),
        relative_path=first_path.relative_to(plans).as_posix(),
        digest=_digest(payload),
    )
    research_candidate = candidate_from_event(
        payload,
        tier="durable",
        root=str(research.resolve()),
        relative_path=second_path.relative_to(research).as_posix(),
        digest=_digest(payload),
    )
    updated = attach_collision_history(
        (plans_candidate, research_candidate),
        collided_digests={_digest(payload), _digest(competitor)},
    )
    commits = {item.evidence.first_commit_id for item in updated}
    assert len(commits) == 2
    for item in updated:
        assert item.evidence.first_commit_id not in item.evidence.ancestor_commit_ids
        assert item.evidence.history_complete is True

    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert len(snapshot.accepted_events) == 1
    assert snapshot.healthy is True


def _outbox_event(store: ArtifactLinkStore, target: str, description: str, op: str):
    return observation_or_put_event_from_row(
        _row(
            source="plan:doc.md",
            relation="related",
            target=target,
            origin="derived",
            description=description,
            created_by="sase",
        ),
        project_key=store.project_key,
        operation_id=op,
    )


def test_empty_store_outbox_collision_restarts_after_rewrite_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": repo},
    )
    operation_id = "f" * 32
    first = _outbox_event(store, "plan:original.md", "first payload", operation_id)
    second = _outbox_event(store, "plan:replay.md", "replay payload", operation_id)
    unrelated = _outbox_event(store, "plan:fresh.md", "unrelated event", "1" * 32)
    for queued in (first, second, unrelated):
        append_artifact_link_outbox_event(
            project_key=store.project_key,
            agent_name="sase",
            run_id="machine",
            event=queued,
        )

    def fail_rewrite(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated interruption before outbox rewrite")

    with monkeypatch.context() as patch:
        patch.setattr(
            "sase.sdd._artifact_link_outbox_drain._rewrite_without_ids",
            fail_rewrite,
        )
        with pytest.raises(RuntimeError, match="before outbox rewrite"):
            drain_artifact_link_outbox(
                store=store,
                drop_stale_terminal=False,
                push_after_commit=False,
            )

    quarantine_paths = list(
        (repo / "link-events" / "quarantine" / "v1").rglob("*.json")
    )
    assert len(quarantine_paths) == 1
    before = quarantine_paths[0].read_bytes()
    assert len(read_artifact_link_outbox_entries(store.project_key)) == 3
    snapshot = store.artifact_link_event_snapshot(strict=True)
    accepted_targets = {_event_target(event) for event in snapshot.accepted_events}
    collision_targets = accepted_targets & {"plan:original.md", "plan:replay.md"}
    assert len(collision_targets) == 1
    accepted_target = next(iter(collision_targets))
    assert "plan:fresh.md" in accepted_targets
    row_targets = {
        row["target_ref"]
        for row in store.load_aggregate()["rows"]
        if isinstance(row, dict)
    }
    assert "plan:fresh.md" in row_targets
    assert accepted_target in row_targets
    assert len(row_targets) == 2
    winner = first if _event_target(first) == accepted_target else second
    winner_path = repo / canonical_artifact_link_event_object(winner).relative_path
    winner_bytes = winner_path.read_bytes()

    restarted = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": repo},
    )
    first_drain = drain_artifact_link_outbox(
        store=restarted,
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert first_drain.quarantined == 1
    assert len(read_artifact_link_outbox_entries(store.project_key)) == 0
    records = list((repo / "link-events" / "quarantine" / "v1").rglob("*.json"))
    assert len(records) == 1
    assert records[0].read_bytes() == before
    assert winner_path.read_bytes() == winner_bytes
    later = restarted.artifact_link_event_snapshot(strict=True)
    assert later.healthy is True
    assert len(later.quarantine_findings) == 1

    second_drain = drain_artifact_link_outbox(
        store=restarted,
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert second_drain.queued == 0
    assert second_drain.quarantined == 0
    assert records[0].read_bytes() == before
    assert winner_path.read_bytes() == winner_bytes
    assert restarted.load_aggregate()["rows"] == store.load_aggregate()["rows"]


def test_rejected_payload_direct_then_outbox_and_reverse_preserve_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": repo},
    )
    first, second = _colliding_pair(origin="derived")
    unrelated = edge_event(
        "b" * 32,
        target="plan:202608/fresh.md",
        description="unrelated append",
        origin="derived",
    )
    report = publish_artifact_link_events(
        store,
        (first, second, unrelated),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert len(report.quarantine_paths) == 1
    before = report.quarantine_paths[0].read_bytes()
    loser_digest = report.quarantined_event_keys[0][1]
    loser = second if _digest(second) == loser_digest else first
    append_artifact_link_outbox_event(
        project_key=store.project_key,
        agent_name="sase",
        run_id="machine",
        event=loser,
    )
    drained = drain_artifact_link_outbox(
        store=store,
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert drained.quarantined == 1
    assert report.quarantine_paths[0].read_bytes() == before

    reverse_root = tmp_path / "reverse"
    reverse_root.mkdir()
    redirect_sase_home(monkeypatch, reverse_root / ".sase")
    reverse_plans = reverse_root / "plans"
    _init_plans_repo(reverse_plans)
    reverse_store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": reverse_plans},
    )
    for queued in (first, second, unrelated):
        append_artifact_link_outbox_event(
            project_key=reverse_store.project_key,
            agent_name="sase",
            run_id="machine",
            event=queued,
        )
    outbox_drain = drain_artifact_link_outbox(
        store=reverse_store,
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert outbox_drain.quarantined == 1
    reverse_records = list(
        (reverse_plans / "link-events" / "quarantine" / "v1").rglob("*.json")
    )
    assert len(reverse_records) == 1
    reverse_before = reverse_records[0].read_bytes()
    reverse_loser_digest = (
        reverse_store.artifact_link_event_snapshot(strict=True)
        .quarantine_findings[0]
        .rejected_digest
    )
    reverse_loser = second if _digest(second) == reverse_loser_digest else first
    retry = publish_artifact_link_events(
        reverse_store,
        (reverse_loser,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert retry.quarantined_event_keys
    assert reverse_records[0].read_bytes() == reverse_before


def test_document_sidecar_and_ownerless_collision_lanes_settle_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_plans_repo(repo)
    sidecar = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": repo},
    )
    first, second = _colliding_pair()
    unrelated = edge_event(
        "b" * 32,
        target="plan:202608/fresh.md",
        description="unrelated append",
    )
    sidecar_report = publish_artifact_link_events(
        sidecar,
        (first, second, unrelated),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert sidecar_report.published_operation_ids == ("a" * 32, "b" * 32)
    assert len(sidecar_report.quarantine_paths) == 1
    sidecar_bytes = sidecar_report.quarantine_paths[0].read_bytes()
    snapshot = sidecar.artifact_link_event_snapshot(strict=True)
    assert snapshot.healthy is True
    assert len(snapshot.quarantine_findings) == 1

    ownerless = ArtifactLinkStore(project_key=PROJECT_KEY, sidecar_roots={})
    local_first = observation_or_put_event_from_row(
        make_row(
            source="agent:reader",
            relation="related",
            target="agent:planner",
            origin="manual",
            description="ownerless original",
        ),
        project_key=PROJECT_KEY,
        operation_id="c" * 32,
    )
    local_second = observation_or_put_event_from_row(
        make_row(
            source="agent:reader",
            relation="related",
            target="agent:other",
            origin="manual",
            description="ownerless replay",
        ),
        project_key=PROJECT_KEY,
        operation_id="c" * 32,
    )
    local_unrelated = observation_or_put_event_from_row(
        make_row(
            source="agent:reader",
            relation="related",
            target="agent:fresh",
            origin="manual",
            description="ownerless unrelated",
        ),
        project_key=PROJECT_KEY,
        operation_id="d" * 32,
    )
    local_report = publish_artifact_link_events(
        ownerless,
        (local_first, local_second, local_unrelated),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert local_report.published == 2
    assert len(local_report.quarantine_paths) == 1
    local_before = local_report.quarantine_paths[0].read_bytes()
    local_loser_digest = local_report.quarantined_event_keys[0][1]
    local_loser = (
        local_second if _digest(local_second) == local_loser_digest else local_first
    )
    local_retry = publish_artifact_link_events(
        ownerless,
        (local_loser,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert local_retry.quarantined_event_keys == local_report.quarantined_event_keys
    assert local_report.quarantine_paths[0].read_bytes() == local_before
    assert sidecar_report.quarantine_paths[0].read_bytes() == sidecar_bytes
