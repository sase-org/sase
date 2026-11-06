"""Settlement completion for keep-work recovery (tale sase-1qz.6.1)."""

from __future__ import annotations

import time
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.recover_reconcile import (
    ReconcileDeps,
    reconcile_recovery,
)
from tests._agent_hijack_recover_reconcile_support import dead_seams, resolving_record


def test_settlement_not_dispatched_returns_to_held(monkeypatch) -> None:
    record = resolving_record(
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
    seams = dead_seams(
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
    record = resolving_record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        launch_stage="prepared",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = dead_seams(observe_admission=lambda rid: {"request_id": rid})
    outcome = reconcile_recovery(record, deps=seams)
    assert outcome["outcome"] == "retain_with_error"
    assert outcome["code"] == "uncertain"


def test_settlement_return_to_held_cas_lost_reports_retain(monkeypatch) -> None:
    from sase.agent.hijack.recover_reconcile import _return_to_held

    record = resolving_record()
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

    first = resolving_record(hijack_id="h-1")
    second = resolving_record(hijack_id="h-2", agent_name="acme--5")
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
    record = resolving_record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        reserved_successor_name="acme--4",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = dead_seams(
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


def test_settlement_resume_queued_returns_queued(monkeypatch) -> None:
    from sase.agent.hijack import recover as recover_module
    from sase.agent.hijack.recover_common import RESULT_QUEUED

    record = resolving_record()
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

    record = resolving_record(state="resolved", revision=9)
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
    record = resolving_record(
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
    outcome = reconcile_recovery(record, deps=dead_seams())
    assert outcome["outcome"] == "return_to_held"
    assert outcome["action_taken"] == "returned_to_held"


def test_settlement_crash_while_queued_keeps_resolving(monkeypatch) -> None:
    record = resolving_record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        launch_stage="prepared",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = dead_seams(
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
    record = resolving_record(
        launch_identity="launch-abc",
        admission_request_id="req-1",
        launch_stage="prepared",
    )
    monkeypatch.setattr(ledger, "load_record", lambda hid: dict(record))
    seams = dead_seams(
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
    record = resolving_record(
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
    record = resolving_record(
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
    record = resolving_record()
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
    seams = dead_seams(
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
