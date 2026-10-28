"""Quarantine replay evidence: quarantine record durability tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_quarantine import (
    load_artifact_link_quarantine_records,
    persist_artifact_link_quarantine_record,
)
from sase.sdd._artifact_link_event_store import reduce_artifact_link_event_inputs
from sase.sdd.artifact_link_event_publisher import publish_artifact_link_events
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_event_store_test_helpers import (
    PROJECT_KEY,
    edge_event,
)
from tests.sdd._artifact_link_quarantine_replay_helpers import (
    colliding_pair,
    commit_all,
    event_digest,
    init_repo,
)
from tests.sdd._artifact_link_store_helpers import allow_machine_sidecar_writes


def _canonical_json(event: dict[str, object]) -> str:
    return str(require_rust_binding("artifact_link_event_canonical_json")(event))


def test_quarantine_reuse_preserves_bytes_across_basis_change(
    tmp_path: Path,
) -> None:
    first, second = colliding_pair()
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

    first, second = colliding_pair()
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
    first, second = colliding_pair()
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

    plans = tmp_path / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    init_repo(plans, monkeypatch)
    (plans / "202609" / "a.md").parent.mkdir(parents=True, exist_ok=True)
    (plans / "202609" / "a.md").write_text("# Doc\n", encoding="utf-8")
    commit_all(plans, "initial doc")

    store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": plans},
    )
    first, second = colliding_pair()
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
    loser = second if event_digest(second) == loser_digest else first
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
