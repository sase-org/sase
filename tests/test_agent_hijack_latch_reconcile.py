"""Identity and evidence rules for stale hijack-latch recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.agent.hijack import _latch_reconcile
from sase.agent.hijack import _latch_reconcile_evidence as evidence


def test_pid_reuse_proves_old_latch_owner_dead(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.ace.hooks.processes.is_process_running", lambda _pid: True
    )
    monkeypatch.setattr(
        "sase.core.process_identity.process_identity_token",
        lambda _pid: "boot:new-process",
    )

    owner, state = evidence.owner_observation(
        {"owner_pid": 42, "owner_identity": "boot:old-process"}
    )

    assert state == "dead"
    assert owner == {
        "lookup_succeeded": True,
        "pid": 42,
        "process_identity": "boot:new-process",
    }


def test_unreadable_owner_identity_remains_unknown(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.ace.hooks.processes.is_process_running", lambda _pid: True
    )
    monkeypatch.setattr(
        "sase.core.process_identity.process_identity_token", lambda _pid: ""
    )

    owner, state = evidence.owner_observation(
        {"owner_pid": 42, "owner_identity": "boot:old-process"}
    )

    assert state == "unknown"
    assert owner["pid"] == 42
    assert owner["process_identity"] is None


def test_adopted_receipt_without_successor_manifest_is_uncertain(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stage_id = "stage-1"
    monkeypatch.setattr(
        "sase.agent.staged_handoff.read_staged_handoff",
        lambda _root: {"staged_id": stage_id},
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.read_adoption_receipt",
        lambda _root: {"staged_id": stage_id, "outcome": "adopted", "refs": {}},
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.read_staged_successor", lambda _root: None
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.receipt_authorizes",
        lambda _receipt, _stage_id: True,
    )

    successor, error = evidence.successor_observation(
        {"agent_name": "agent.1", "owner_identity": "boot:old"}, str(tmp_path)
    )

    assert successor["kind"] == "uncertain"
    assert "no successor manifest" in str(error)


def test_stale_recovery_scans_ledger_records_without_live_rows(
    monkeypatch: Any,
) -> None:
    record = {"hijack_id": "h-1", "state": "latched"}
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(
        _latch_reconcile.ledger, "list_active_records", lambda: [record]
    )
    monkeypatch.setattr(
        _latch_reconcile,
        "_reconcile_record",
        lambda value, **_kwargs: seen.append(value),
    )

    _latch_reconcile.reconcile_latched_records()

    assert seen == [record]
