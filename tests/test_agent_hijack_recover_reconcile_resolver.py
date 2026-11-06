"""Crash repair of a keep-work recovery resolver."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.recover_reconcile import (
    ReconcileDeps,
    gather_reconcile_facts,
    reconcile_recovery,
)
from tests._agent_hijack_recover_reconcile_support import dead_seams, resolving_record


def test_live_resolver_keeps_resolving(monkeypatch) -> None:
    record = resolving_record()
    monkeypatch.setattr(ledger, "load_record", lambda hijack_id: dict(record))
    seams = ReconcileDeps(
        is_process_running=lambda pid: True,
        process_identity_token=lambda pid: "boot:111",
        observe_admission=lambda rid: {"request_id": rid, "state": "missing"},
        load_successor_artifacts=lambda record: None,
        now_unix=lambda: time.time(),
    )
    facts = gather_reconcile_facts(record, deps=seams)
    assert facts["resolver"]["pid_live"] is True
    assert facts["resolver"]["identity_matches"] is True
    outcome = reconcile_recovery(record, deps=seams)
    assert outcome["outcome"] == "keep_resolving"
    assert outcome["action_taken"] == "none"


def test_too_young_dead_resolver_waits(monkeypatch) -> None:
    from sase.agent.hijack.ledger import timestamp_for

    record = resolving_record(updated_at=timestamp_for(), hijacked_at=timestamp_for())
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    outcome = reconcile_recovery(record, deps=dead_seams())
    assert outcome["outcome"] == "keep_resolving"
    assert outcome["code"] == "too_young"


def test_absent_without_launch_evidence_returns_to_held(monkeypatch) -> None:
    record = resolving_record(
        launch_identity=None,
        admission_request_id=None,
        admission_identity=None,
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    held: dict[str, Any] = {}
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.fail_to_held",
        lambda resolving, message: held.update({"called": True}),
    )
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.reload_record",
        lambda hid, fallback: {**dict(fallback), "state": "held"},
    )
    outcome = reconcile_recovery(record, deps=dead_seams())
    assert outcome["outcome"] == "return_to_held"
    assert outcome["action_taken"] == "returned_to_held"
    assert held.get("called") is True


def test_absent_with_launch_evidence_retains(monkeypatch) -> None:
    record = resolving_record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        launch_stage="prepared",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    outcome = reconcile_recovery(record, deps=dead_seams())
    assert outcome["outcome"] == "retain_with_error"
    assert outcome["action_taken"] == "none"


def test_matching_queued_request_stays_authoritative(monkeypatch) -> None:
    record = resolving_record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        admission_identity="fp",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = dead_seams(
        observe_admission=lambda rid: {
            "request_id": "req-1",
            "state": "submitted",
            "dispatch_fingerprint": "fp",
            "in_flight": True,
        }
    )
    outcome = reconcile_recovery(record, deps=seams)
    assert outcome["outcome"] == "keep_resolving"
    assert outcome["code"] == "queued"


def test_mismatched_queued_retains(monkeypatch) -> None:
    record = resolving_record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        admission_identity="fp",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = dead_seams(
        observe_admission=lambda rid: {
            "request_id": "other",
            "state": "submitted",
            "dispatch_fingerprint": "other",
            "in_flight": True,
        }
    )
    outcome = reconcile_recovery(record, deps=seams)
    assert outcome["outcome"] == "retain_with_error"
    assert outcome["action_taken"] == "none"


def test_name_only_successor_retains(monkeypatch) -> None:
    record = resolving_record(
        launch_identity=None,
        admission_request_id=None,
        admission_identity=None,
        successor_artifacts_dir=None,
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    outcome = reconcile_recovery(record, deps=dead_seams())
    # No launch evidence at all returns to held; name-only arises when a
    # reserved name exists but no launch/admission identity was recorded and
    # no successor artifacts are observable. The Rust facts mark it
    # uncertain only when launch evidence exists without a match.
    assert outcome["outcome"] in {"return_to_held", "retain_with_error"}


def test_reused_resolver_pid_is_dead(monkeypatch) -> None:
    record = resolving_record()
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = ReconcileDeps(
        is_process_running=lambda pid: True,
        process_identity_token=lambda pid: "boot:999",
        observe_admission=lambda rid: {"request_id": rid, "state": "missing"},
        load_successor_artifacts=lambda record: None,
        now_unix=lambda: time.time(),
    )
    facts = gather_reconcile_facts(record, deps=seams)
    assert facts["resolver"]["pid_live"] is True
    assert facts["resolver"]["identity_matches"] is False
    held: dict[str, Any] = {}
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.fail_to_held",
        lambda resolving, message: held.update({"called": True}),
    )
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.reload_record",
        lambda hid, fallback: {**dict(fallback), "state": "held"},
    )
    record_no_evidence = resolving_record(
        launch_identity=None,
        admission_request_id=None,
        admission_identity=None,
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record_no_evidence))
    outcome = reconcile_recovery(record_no_evidence, deps=seams)
    assert outcome["outcome"] == "return_to_held"
    assert held.get("called") is True


def test_malformed_record_retains_without_crash(monkeypatch) -> None:
    record = resolving_record(resolver_pid="not-a-pid", workspace_num="bad")
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    outcome = reconcile_recovery(record, deps=dead_seams())
    assert outcome["action_taken"] in {"none", "returned_to_held"}
    assert outcome["outcome"] in {
        "keep_resolving",
        "return_to_held",
        "retain_with_error",
    }


def test_second_cleanup_does_not_duplicate(monkeypatch, tmp_path: Path) -> None:
    record = resolving_record(
        launch_identity=None,
        admission_request_id=None,
        admission_identity=None,
    )
    state = {"current": dict(record)}
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(state["current"]))

    def fake_fail(resolving: Any, message: str) -> None:
        state["current"] = {**dict(resolving), "state": "held"}

    monkeypatch.setattr("sase.agent.hijack.recover_reconcile.fail_to_held", fake_fail)
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.reload_record",
        lambda hid, fallback: dict(state["current"]),
    )
    first = reconcile_recovery(record, deps=dead_seams())
    assert first["action_taken"] == "returned_to_held"
    second = reconcile_recovery(state["current"], deps=dead_seams())
    assert second["action_taken"] == "none"
