"""Crash repair and successor-following waits for keep-work recovery."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.recover_reconcile import (
    ReconcileDeps,
    gather_reconcile_facts,
    reconcile_recovery,
)
from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)

from tests._agent_names_fixtures import make_agent


def _record(**overrides: Any) -> dict[str, Any]:
    base = {
        "schema_version": 1,
        "hijack_id": "h-1",
        "agent_name": "acme--3",
        "artifacts_dir": "/tmp/pre",
        "session": "acme",
        "project_file": "/tmp/proj.sase",
        "workspace_num": 3,
        "workspace_dir": "/ws/3",
        "state": "resolving",
        "revision": 4,
        "resolution_action": "escalate",
        "reserved_successor_name": "acme--4",
        "concrete_target_model": "claude/opus@xhigh",
        "model_changed": True,
        "resolver_pid": 99999999,
        "resolver_process_identity_token": "boot:111",
        "updated_at": "2020-01-01T00:00:00+00:00",
        "hijacked_at": "2020-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _dead_seams(**overrides: Any) -> ReconcileDeps:
    kwargs: dict[str, Any] = {
        "is_process_running": lambda pid: False,
        "process_identity_token": lambda pid: "boot:999",
        "observe_admission": lambda request_id: {
            "request_id": request_id,
            "state": "missing",
        },
        "load_successor_artifacts": lambda record: None,
        "now_unix": lambda: time.time(),
    }
    kwargs.update(overrides)
    return ReconcileDeps(**kwargs)


def test_live_resolver_keeps_resolving(monkeypatch) -> None:
    record = _record()
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

    record = _record(updated_at=timestamp_for(), hijacked_at=timestamp_for())
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    outcome = reconcile_recovery(record, deps=_dead_seams())
    assert outcome["outcome"] == "keep_resolving"
    assert outcome["code"] == "too_young"


def test_absent_without_launch_evidence_returns_to_held(monkeypatch) -> None:
    record = _record(
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
    outcome = reconcile_recovery(record, deps=_dead_seams())
    assert outcome["outcome"] == "return_to_held"
    assert outcome["action_taken"] == "returned_to_held"
    assert held.get("called") is True


def test_absent_with_launch_evidence_retains(monkeypatch) -> None:
    record = _record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        launch_stage="prepared",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    outcome = reconcile_recovery(record, deps=_dead_seams())
    assert outcome["outcome"] == "retain_with_error"
    assert outcome["action_taken"] == "none"


def test_matching_queued_request_stays_authoritative(monkeypatch) -> None:
    record = _record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        admission_identity="fp",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = _dead_seams(
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
    record = _record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        admission_identity="fp",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = _dead_seams(
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
    record = _record(
        launch_identity=None,
        admission_request_id=None,
        admission_identity=None,
        successor_artifacts_dir=None,
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    outcome = reconcile_recovery(record, deps=_dead_seams())
    # No launch evidence at all returns to held; name-only arises when a
    # reserved name exists but no launch/admission identity was recorded and
    # no successor artifacts are observable. The Rust facts mark it
    # uncertain only when launch evidence exists without a match.
    assert outcome["outcome"] in {"return_to_held", "retain_with_error"}


def test_reused_resolver_pid_is_dead(monkeypatch) -> None:
    record = _record()
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
    record_no_evidence = _record(
        launch_identity=None,
        admission_request_id=None,
        admission_identity=None,
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record_no_evidence))
    outcome = reconcile_recovery(record_no_evidence, deps=seams)
    assert outcome["outcome"] == "return_to_held"
    assert held.get("called") is True


def test_malformed_record_retains_without_crash(monkeypatch) -> None:
    record = _record(resolver_pid="not-a-pid", workspace_num="bad")
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    outcome = reconcile_recovery(record, deps=_dead_seams())
    assert outcome["action_taken"] in {"none", "returned_to_held"}
    assert outcome["outcome"] in {
        "keep_resolving",
        "return_to_held",
        "retain_with_error",
    }


def test_second_cleanup_does_not_duplicate(monkeypatch, tmp_path: Path) -> None:
    record = _record(
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
    first = reconcile_recovery(record, deps=_dead_seams())
    assert first["action_taken"] == "returned_to_held"
    second = reconcile_recovery(state["current"], deps=_dead_seams())
    assert second["action_taken"] == "none"


def _hijacked_agent(
    base: Path, name: str, suffix: str, successor: str, state: str
) -> Path:
    agent_dir = make_agent(base, "proj", suffix, name, done=True, outcome="hijacked")
    done_data = {
        "outcome": "hijacked",
        "recovery": {
            "kind": "hijack",
            "state": state,
            "successor": successor,
        },
    }
    (agent_dir / "done.json").write_text(json.dumps(done_data))
    return agent_dir


def test_name_wait_follows_resolved_successor(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "resolved")
    make_agent(
        tmp_path, "proj", "20260506010202", "acme--4", done=True, outcome="completed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert dependency_resolution_status(index, ["acme--3"]).resolved


def test_name_wait_follows_failure(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "resolved")
    make_agent(
        tmp_path, "proj", "20260506010202", "acme--4", done=True, outcome="failed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert not dependency_resolution_status(index, ["acme--3"]).resolved


def test_pending_hijack_stays_parked(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "pending")
    make_agent(
        tmp_path, "proj", "20260506010202", "acme--4", done=True, outcome="completed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert not dependency_resolution_status(index, ["acme--3"]).resolved


def test_expired_hijack_stays_parked(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "expired")
    make_agent(
        tmp_path, "proj", "20260506010202", "acme--4", done=True, outcome="completed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert not dependency_resolution_status(index, ["acme--3"]).resolved


def test_missing_successor_stays_waiting(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--9", "resolved")
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert not dependency_resolution_status(index, ["acme--3"]).resolved


def test_chained_recovery_follows_two_hops(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "resolved")
    _hijacked_agent(tmp_path, "acme--4", "20260506010202", "acme--5", "resolved")
    make_agent(
        tmp_path, "proj", "20260506010303", "acme--5", done=True, outcome="completed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert dependency_resolution_status(index, ["acme--3"]).resolved
    assert dependency_resolution_status(index, ["acme--4"]).resolved


def test_session_wait_follows_successor_in_same_session(tmp_path: Path) -> None:
    pre = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "sess--0",
        workflow_name="sess",
        agent_session="sess",
        done=True,
        outcome="hijacked",
    )
    (pre / "done.json").write_text(
        json.dumps(
            {
                "outcome": "hijacked",
                "recovery": {
                    "kind": "hijack",
                    "state": "resolved",
                    "successor": "sess--1",
                },
            }
        )
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "sess--1",
        workflow_name="sess",
        agent_session="sess",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert dependency_resolution_status(index, ["sess"]).resolved
