"""Request and target-resolution contracts for agent hijack latches."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack import ledger, latch
from sase.agent.hijack import _latch_common as latch_common
from sase.agent.hijack._stop_models import HijackTarget
from tests._agent_hijack_latch_support import (
    install_subjects,
    make_subject,
    make_target,
    shared_latch_store,
)

__all__ = ["shared_latch_store"]


def make_monitor_target(
    artifacts: Path,
    *,
    name: str = "session-1--mon-3",
    pid: int | None = 42,
    identity: str = "boot:123",
    monitor_state: str = "running",
) -> HijackTarget:
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": name,
                "agent_session": "session-1",
                "turn_kind": "monitor",
                "monitor_id": "mon-3",
                "monitor_state": monitor_state,
                "monitor_supervisor_identity": identity,
                "process_identity": identity,
                "pid": pid,
            }
        ),
        encoding="utf-8",
    )
    target = HijackTarget(
        name=name,
        artifacts_dir=str(artifacts),
        project_name="sample",
        project_file="/tmp/sample.sase",
        artifacts_timestamp="20261116000100",
        is_home=False,
        pid=pid,
        claim_pid=pid or 42,
        claim_pinned=False,
        cl_name="sample-patch",
        workflow="agent",
        workspace_num=4,
        workspace_dir="/tmp/workspace-4",
        status="RUNNING" if monitor_state == "running" else "DONE",
        lifecycle_phase=None,
        is_monitor_turn=True,
        is_gate_turn=False,
        gate_state=None,
        agent_session="session-1",
        capabilities=[],
        model_alias=None,
        model_alias_trail=[],
        model_origin=None,
        provider=None,
        model=None,
        effort=None,
        run_started_at=10.0,
        done_outcome=None if monitor_state == "running" else "succeeded",
        done_recovery=None,
        monitor_id="mon-3",
        monitor_supervisor_identity=identity,
    )
    target.test_identity = identity
    return target


def test_monitor_latch_request_uses_monitor_scope(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del latch_store
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    target = make_monitor_target(tmp_path / "monitor")
    install_subjects(monkeypatch, make_subject(target))
    first = latch.request_latch(target.name)
    assert first["verdict"] == "pending"
    assert first["record"]["scope"] == "monitor"
    assert first["record"]["owner_identity"] == "boot:123"

    install_subjects(monkeypatch, make_subject(target))
    second = latch.request_latch(target.name)
    assert second["verdict"] == "pending"
    assert second["hijack_id"] == first["hijack_id"]
    assert len(ledger.list_active_records()) == 1


def test_pending_followup_monitor_latch_applies_at_request(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del latch_store
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    target = make_monitor_target(tmp_path / "monitor", monitor_state="completed")
    install_subjects(
        monkeypatch,
        make_subject(
            target,
            settled=True,
            process_alive=False,
            monitor_followup_pending=True,
        ),
    )

    def fake_settle(
        artifacts_dir: str,
        _meta: dict[str, Any],
        *,
        monitor_state: str,
        project_name: str | None,
    ) -> Any:
        del artifacts_dir, project_name
        current = ledger.list_active_records()[0]
        current = ledger.cas_advance_record(
            current,
            {
                "event": "apply_latch",
                "boundary": "monitor",
                "boundary_outcome": monitor_state,
            },
        )
        current = ledger.cas_advance_record(current, {"event": "confirmed_stop"})
        return SimpleNamespace(
            settled=True,
            handled=True,
            error=None,
            hijack_id=current["hijack_id"],
        )

    monkeypatch.setattr(
        "sase.monitor.hijack_settlement.settle_monitor_hijack", fake_settle
    )
    result = latch.request_latch(target.name)
    assert result["verdict"] == "applied"
    assert result["record"]["state"] == "held"
    assert result["record"]["scope"] == "monitor"
    assert result["boundary"] == "monitor"


def test_delivered_monitor_latch_is_refused(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del latch_store
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    target = make_monitor_target(
        tmp_path / "monitor", pid=None, monitor_state="completed"
    )
    install_subjects(
        monkeypatch,
        make_subject(target, settled=True, process_alive=False),
    )
    result = latch.request_latch(target.name)
    assert result["verdict"] == "refused"
    assert result["code"] == "owner_not_live"
    assert ledger.list_active_records() == []


def test_gate_latch_is_still_refused(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del latch_store
    target = make_target(tmp_path / "gate")
    target.is_gate_turn = True
    install_subjects(monkeypatch, make_subject(target))
    result = latch.request_latch(target.name)
    assert result["verdict"] == "refused"
    assert result["code"] == "unsupported_target"


def test_request_deduplicates_by_target_and_rejects_recycled_occupant(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path / "member-a")
    install_subjects(monkeypatch, make_subject(target))
    first = latch.request_latch(target.name)
    assert first["verdict"] == "pending"
    assert first["record"]["owner_identity"] == "boot:123"
    assert first["record"]["provider"] == target.provider
    assert first["record"]["model"] == target.model
    assert first["record"]["effort"] == target.effort

    install_subjects(monkeypatch, make_subject(target))
    second = latch.request_latch(target.name)
    assert second["verdict"] == "pending"
    assert second["hijack_id"] == first["hijack_id"]
    assert len(ledger.list_active_records()) == 1

    replacement = make_target(
        tmp_path / "member-b", name=target.name, pid=99, identity="boot:999"
    )
    install_subjects(monkeypatch, make_subject(replacement))
    changed = latch.request_latch(target.name)
    assert changed["verdict"] == "ownership_uncertain"
    assert changed["hijack_id"] == first["hijack_id"]
    assert len(ledger.list_active_records()) == 1


def test_second_resolution_change_releases_unwritten_reservation(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_target = make_target(tmp_path / "member-a")
    changed_target = make_target(
        tmp_path / "member-b", name="agent.2", pid=99, identity="boot:999"
    )
    install_subjects(
        monkeypatch, make_subject(first_target), make_subject(changed_target)
    )
    result = latch.request_latch(first_target.name)
    assert result["code"] == "occupant_changed"
    assert ledger.list_active_records() == []
    assert (
        ledger.find_active_record_by_target_key(
            ledger.target_key_for("/tmp/sample.sase", "session-1")
        )
        is None
    )


def test_cancel_and_moot_release_only_their_own_target_reservation(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path / "member")
    install_subjects(monkeypatch, make_subject(target))
    requested = latch.request_latch(target.name)
    cancelled = latch.cancel_latch(
        str(requested["target_key"]), hijack_id=str(requested["hijack_id"])
    )
    assert cancelled["verdict"] == "cancelled"
    assert cancelled["record"]["state"] == "cancelled"
    assert ledger.find_active_record_by_target_key(str(requested["target_key"])) is None
    observed = latch.observe_hijack_latch(
        str(requested["target_key"]),
        "run_end",
        member=target.name,
        artifacts_dir=target.artifacts_dir,
        owner_pid=target.pid,
        owner_identity="boot:123",
        hijack_id=str(requested["hijack_id"]),
    )
    assert observed["verdict"] == "cancelled"

    target2 = make_target(tmp_path / "member-2", name="agent.2")
    install_subjects(monkeypatch, make_subject(target2))
    requested2 = latch.request_latch(target2.name)
    monkeypatch.setattr(latch_common, "owner_identity_for", lambda _target: None)
    mooted = latch.moot_latch(
        str(requested2["target_key"]),
        "run_end",
        "completed",
        target=target2,
    )
    assert mooted["verdict"] == "moot"
    assert mooted["record"]["boundary_outcome"] == "completed"
    assert (
        ledger.find_active_record_by_target_key(str(requested2["target_key"])) is None
    )
