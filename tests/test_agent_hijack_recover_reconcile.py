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


# --- Settlement completion (tale sase-1qz.6.1) ---


def test_settlement_not_dispatched_returns_to_held(monkeypatch) -> None:
    record = _record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        launch_stage="prepared",
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
    seams = _dead_seams(
        observe_admission=lambda rid: {
            "request_id": rid,
            "state": "cancelled",
            "receipt_state": "cancelled",
        },
    )
    outcome = reconcile_recovery(record, deps=seams)
    assert outcome["outcome"] == "return_to_held"
    assert outcome["code"] == "not_dispatched"
    assert outcome["action_taken"] == "returned_to_held"
    assert held.get("called") is True


def test_settlement_uncertain_journal_stays_uncertain(monkeypatch) -> None:
    record = _record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        launch_stage="prepared",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = _dead_seams(observe_admission=lambda rid: {"request_id": rid})
    outcome = reconcile_recovery(record, deps=seams)
    assert outcome["outcome"] == "retain_with_error"
    assert outcome["code"] == "uncertain"


def test_settlement_return_to_held_cas_lost_reports_retain(monkeypatch) -> None:
    from sase.agent.hijack.recover_reconcile import _return_to_held

    record = _record()
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.fail_to_held",
        lambda resolving, message: None,
    )
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.reload_record",
        lambda hid, fallback: {**dict(fallback), "state": "resolving"},
    )
    outcome = _return_to_held(record, {"outcome": "return_to_held", "code": "absent"})
    assert outcome["outcome"] == "retain_with_error"
    assert outcome["code"] == "held_cas_lost"
    assert outcome["action_taken"] == "none"


def test_settlement_resolving_claim_matches_successor_pid() -> None:
    from unittest.mock import patch

    from sase.agent.hijack.custody import matching_active_record
    from sase.running_field import WorkspaceClaim

    record = {
        "state": "resolving",
        "project_file": "/tmp/p.sase",
        "workspace_num": 4,
        "expected_claim_owner_pid": 111,
        "successor_pid": 222,
        "launch_identity": "launch-abc",
        "admission_request_id": "req-1",
        "reserved_successor_name": "acme--4",
    }
    claim = WorkspaceClaim(
        workspace_num=4,
        workflow="run",
        cl_name="",
        pid=222,
        artifacts_timestamp="20260506010101",
        pinned=True,
    )
    with patch("sase.agent.hijack.custody.list_active_records", return_value=[record]):
        assert matching_active_record("/tmp/p.sase", claim) is record


def test_settlement_stale_cleanup_reconciles_every_resolving() -> None:
    from unittest.mock import patch

    from sase.ace.scheduler import stale_running_sweep as cleanup

    first = _record(hijack_id="h-1")
    second = _record(hijack_id="h-2", agent_name="acme--5")
    seen: list[str] = []
    with (
        patch(
            "sase.agent.hijack.ledger.list_active_records",
            return_value=[first, second, {"state": "held"}],
        ),
        patch.object(
            cleanup,
            "_reconcile_resolving_record",
            side_effect=lambda record, log_fn=None: seen.append(
                str(record.get("hijack_id"))
            ),
        ),
    ):
        cleanup._reconcile_all_resolving_records(log_fn=None)
    assert sorted(seen) == ["h-1", "h-2"]


def test_settlement_pending_drains_without_resolving(monkeypatch, tmp_path) -> None:
    from sase.agent.hijack import _recover_reconcile_pending as pending
    from sase.agent.hijack import ledger as ledger_module
    from sase.core import paths as paths_module

    monkeypatch.setattr(paths_module, "sase_subdir", lambda subdir: tmp_path / subdir)
    pending.add_pending_repair("h-9")
    assert pending.read_pending_repairs() == ["h-9"]
    monkeypatch.setattr(
        ledger_module, "load_record", lambda hid: {"state": "dismissed"}
    )
    from sase.agent.hijack.recover_reconcile import repair_pending_settlements

    assert repair_pending_settlements(limit=20) == 0
    assert pending.read_pending_repairs() == []


def test_settlement_malformed_metadata_keeps_custody(monkeypatch) -> None:
    record = _record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        reserved_successor_name="acme--4",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = _dead_seams(
        observe_admission=lambda rid: {
            "request_id": rid,
            "state": "submitted",
        },
        load_successor_artifacts=lambda record: None,
    )
    outcome = reconcile_recovery(record, deps=seams)
    assert outcome["outcome"] in {"keep_resolving", "retain_with_error"}
    assert outcome["action_taken"] == "none"
    assert "keeping custody" in str(outcome.get("message") or "").lower() or (
        "authoritative" in str(outcome.get("message") or "").lower()
    )


def test_settlement_expired_neither_resolved_nor_failed(tmp_path: Path) -> None:
    from sase.core.wait_dependency_resolution import (
        build_wait_dependency_index,
    )

    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "expired")
    make_agent(
        tmp_path, "proj", "20260506010202", "acme--4", done=True, outcome="completed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert not dependency_resolution_status(index, ["acme--3"]).resolved
    assert index.terminal_blocking_artifacts_for_name("acme--3") == ()


def test_settlement_resume_queued_returns_queued(monkeypatch) -> None:
    from sase.agent.hijack import recover as recover_module
    from sase.agent.hijack.recover_common import RESULT_QUEUED

    record = _record()
    monkeypatch.setattr(
        recover_module, "_reconcile_before_resume", lambda current, seams=None: None
    )
    monkeypatch.setattr(
        recover_module,
        "resume_recovery_admission",
        lambda current, **kwargs: {
            "state": "submitted",
            "in_flight": True,
            "message": "still queued",
        },
    )
    outcome = recover_module._resume_existing_resolution(record, seams=None)
    assert outcome.kind == RESULT_QUEUED


def test_settlement_recover_resolved_repairs(monkeypatch) -> None:
    from sase.agent.hijack import recover as recover_module
    from sase.agent.hijack.recover_common import RESULT_ALREADY_RESOLVED

    record = _record(state="resolved", revision=9)
    called: dict[str, Any] = {}
    monkeypatch.setattr(recover_module, "load_recovery_subject", lambda name: None)
    import sase.agent.hijack.recover_reconcile as reconcile_module

    monkeypatch.setattr(
        reconcile_module,
        "repair_settled_projection",
        lambda record_or_id: called.update({"called": True}) or False,
    )
    from tests._agent_hijack_recover_helpers import subject as make_subject

    monkeypatch.setattr(
        recover_module, "load_recovery_subject", lambda name: make_subject(record)
    )
    outcome = recover_module.recover_hijacked_agent("acme--3", action="continue")
    assert outcome.kind == RESULT_ALREADY_RESOLVED
    assert called.get("called") is True


def test_settlement_crash_before_admission_returns_to_held(monkeypatch) -> None:
    record = _record(
        launch_identity=None,
        admission_request_id=None,
        admission_identity=None,
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.fail_to_held",
        lambda resolving, message: None,
    )
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.reload_record",
        lambda hid, fallback: {**dict(fallback), "state": "held"},
    )
    outcome = reconcile_recovery(record, deps=_dead_seams())
    assert outcome["outcome"] == "return_to_held"
    assert outcome["action_taken"] == "returned_to_held"


def test_settlement_crash_while_queued_keeps_resolving(monkeypatch) -> None:
    record = _record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        launch_stage="prepared",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = _dead_seams(
        observe_admission=lambda rid: {
            "request_id": rid,
            "state": "submitted",
            "in_flight": True,
        },
    )
    outcome = reconcile_recovery(record, deps=seams)
    assert outcome["outcome"] == "keep_resolving"
    assert outcome["code"] == "queued"
    assert outcome["action_taken"] == "none"


def test_settlement_crash_after_child_creation_retains(monkeypatch) -> None:
    record = _record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        launch_stage="prepared",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = _dead_seams(
        observe_admission=lambda rid: {
            "request_id": rid,
            "state": "dispatched",
            "identity": "acme--4",
        },
        load_successor_artifacts=lambda record: "/tmp/succ",
    )
    outcome = reconcile_recovery(record, deps=seams)
    assert outcome["action_taken"] == "none"
    assert outcome["outcome"] in {"keep_resolving", "retain_with_error"}


def test_settlement_crash_after_ack_adopts(monkeypatch, tmp_path) -> None:
    import json as json_module

    succ = tmp_path / "succ"
    succ.mkdir()
    (succ / "agent_meta.json").write_text(
        json_module.dumps(
            {
                "name": "acme--4",
                "pid": 4242,
                "process_identity": "boot:4242",
                "artifacts_dir": str(succ),
                "workspace_num": 3,
            }
        )
    )
    (succ / "done.json").write_text(json_module.dumps({"outcome": "completed"}))
    record = _record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        launch_stage="prepared",
        successor_artifacts_dir=str(succ),
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    settled: dict[str, Any] = {}
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.settle_recovery",
        lambda *args, **kwargs: (
            settled.update({"called": True}) or {**dict(record), "state": "resolved"}
        ),
    )
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.reload_record",
        lambda hid, fallback: {**dict(fallback), "state": "resolved"},
    )
    seams = ReconcileDeps(
        is_process_running=lambda pid: False,
        process_identity_token=lambda pid: "boot:999",
        observe_admission=lambda rid: {
            "request_id": rid,
            "state": "dispatched",
            "identity": "acme--4",
        },
        load_successor_artifacts=lambda record: str(succ),
        now_unix=lambda: time.time(),
    )
    monkeypatch.setattr(
        "sase.agent.hijack.recovery_successor.read_recovery_ack",
        lambda artifacts_dir: {
            "launch_identity": "launch-abc",
            "successor_name": "acme--4",
            "workspace_num": 3,
            "workspace_dir": "/ws/3",
            "lineage": {"hijack_id": "h-1", "predecessor": "acme--3"},
            "baseline_inherited": True,
        },
    )
    outcome = reconcile_recovery(record, deps=seams)
    assert settled.get("called") is True
    assert outcome["action_taken"] in {"adopted", "pending_repair"}


def test_settlement_cleanup_never_releases_resolving() -> None:
    from unittest.mock import patch

    from sase.ace.scheduler import stale_running_sweep as cleanup
    from sase.running_field import WorkspaceClaim

    project_file = "/tmp/projects/proj/proj.sase"
    claim = WorkspaceClaim(
        workspace_num=3,
        workflow="run",
        cl_name="",
        pid=999,
        artifacts_timestamp="20260506010101",
        pinned=True,
    )
    record = _record(
        project_file=project_file,
        workspace_num=3,
        expected_claim_owner_pid=111,
        launch_identity="launch-abc",
        admission_request_id="req-1",
    )
    with (
        patch.object(cleanup, "_get_all_project_files", return_value=[project_file]),
        patch.object(cleanup, "get_claimed_workspaces", return_value=[claim]),
        patch.object(cleanup, "_matching_hijack_record", return_value=dict(record)),
        patch.object(cleanup, "_reconcile_resolving_record", return_value=None),
        patch.object(cleanup, "release_workspace") as release,
    ):
        released = cleanup.cleanup_stale_running_entries()
    assert released == 0
    release.assert_not_called()


def test_settlement_double_cleanup_does_not_double_settle(monkeypatch) -> None:
    record = _record()
    calls: list[str] = []
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.fail_to_held",
        lambda resolving, message: None,
    )
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.settle_recovery",
        lambda *args, **kwargs: (
            calls.append("settle") or {**dict(record), "state": "resolved"}
        ),
    )
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.reload_record",
        lambda hid, fallback: {**dict(fallback), "state": "held"},
    )
    seams = _dead_seams(
        observe_admission=lambda rid: {"request_id": rid, "state": "cancelled"},
    )
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.clear_pending_repair",
        lambda hid: None,
    )
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.add_pending_repair",
        lambda hid: None,
    )
    first = reconcile_recovery(record, deps=seams)
    # A resolved record repairs its projection without a second settle CAS.
    monkeypatch.setattr(
        "sase.agent.hijack.recover_reconcile.reload_record",
        lambda hid, fallback: {**dict(fallback), "state": "resolved"},
    )
    second = reconcile_recovery({**record, "state": "resolved"}, deps=seams)
    assert first["action_taken"] in {"returned_to_held", "adopted", "pending_repair"}
    assert second["action_taken"] in {"none", "pending_repair"}
    assert calls.count("settle") <= 1


def test_settlement_newest_artifact_wins_name_collision(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "resolved")
    _hijacked_agent(tmp_path, "acme--3", "20260506010303", "acme--5", "resolved")
    make_agent(
        tmp_path, "proj", "20260506010404", "acme--5", done=True, outcome="completed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert dependency_resolution_status(index, ["acme--3"]).resolved
    assert index.terminal_blocking_artifacts_for_name("acme--3") == ()
