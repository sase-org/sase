"""Monitor-specific stop and settlement for Agent Hijack custody."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack._stop_models import HijackTarget, StopDeps
from sase.agent.hijack.stop import stop_agent_for_hijack
from sase.monitor.models import MonitorRecord
from sase.monitor.output import OutputCapture
from sase.monitor.settlement import settle_claim_and_followup
from sase.running_field import get_claimed_workspaces
from tests.monitor._retention_fixtures import (
    init_retention_repo,
    make_retention_monitor,
    read_retention_meta,
    write_retention_meta,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _monitor_target(
    artifacts_dir: str,
    project_file: str,
    repo: Path,
    meta: dict[str, Any],
) -> HijackTarget:
    timestamp = Path(artifacts_dir).name
    return HijackTarget(
        name=str(meta["name"]),
        artifacts_dir=artifacts_dir,
        project_name="proj",
        project_file=project_file,
        artifacts_timestamp=timestamp,
        is_home=False,
        pid=os.getpid(),
        claim_pid=os.getpid(),
        claim_pinned=False,
        cl_name="acme",
        workflow="ace-monitor",
        workspace_num=3,
        workspace_dir=str(repo),
        status="RUNNING",
        lifecycle_phase=None,
        is_monitor_turn=True,
        is_gate_turn=False,
        gate_state=None,
        agent_session="acme",
        capabilities=[],
        model_alias=None,
        model_alias_trail=[],
        model_origin=None,
        provider=None,
        model="test",
        effort=None,
        run_started_at=None,
        done_outcome=None,
        done_recovery=None,
        monitor_id=str(meta["monitor_id"]),
        monitor_supervisor_identity=str(meta["monitor_supervisor_identity"]),
    )


def _write_meta(artifacts_dir: str, meta: dict[str, Any], **_kwargs: Any) -> None:
    Path(artifacts_dir, "agent_meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )


def test_monitor_hijack_uses_stop_adapter_and_keeps_exact_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent import _user_kill_intent
    from sase.agent.hijack import _stop_evidence, ledger
    from sase.axe import agent_meta as agent_meta_module
    from sase.axe import run_agent_exec_markers

    repo = init_retention_repo(tmp_path / "workspace", dirty=False)
    artifacts_dir, project_file = make_retention_monitor(
        repo, monitor_state="running", next_action="Report the command result."
    )
    meta = read_retention_meta(artifacts_dir)
    meta.update(
        {
            "monitor_supervisor_identity": "test-boot:71",
            "project_file": project_file,
            "project_name": "proj",
            "monitor_execution_argv": ["/bin/true"],
            "monitor_timeout_seconds": 30.0,
            "monitor_output_path": str(Path(artifacts_dir) / "monitor.log"),
        }
    )
    write_retention_meta(artifacts_dir, meta)
    target = _monitor_target(artifacts_dir, project_file, repo, meta)
    subject = SimpleNamespace(
        target=target,
        occupant_name=target.name,
        occupant_reason="monitor holds workspace #3",
        session=SimpleNamespace(base_name="acme"),
    )
    decision = {
        "mode": "immediate",
        "eligible": True,
        "adapter": "monitor",
        "code": "monitor_running",
        "message": "running monitor can be stopped",
    }
    monkeypatch.setattr(
        "sase.agent.hijack.facts.resolve_and_decide",
        lambda _name, deps=None: (subject, decision),
    )
    custody_pid = os.getpid() + 200_000
    write_intent = _user_kill_intent.write_user_kill_intent

    def write_intent_with_test_custodian(*args: Any, **kwargs: Any) -> Any:
        kwargs["custody_pid"] = custody_pid
        return write_intent(*args, **kwargs)

    monkeypatch.setattr(
        _user_kill_intent, "write_user_kill_intent", write_intent_with_test_custodian
    )
    monkeypatch.setattr(
        agent_meta_module,
        "write_agent_meta_atomic",
        lambda path, value, **kwargs: _write_meta(str(path), dict(value), **kwargs),
    )
    monkeypatch.setattr(
        run_agent_exec_markers,
        "write_done_marker_and_update_index",
        lambda path, marker: Path(path, "done.json").write_text(
            json.dumps(marker), encoding="utf-8"
        ),
    )
    monkeypatch.setattr(
        _stop_evidence,
        "collect_and_attach_evidence",
        lambda hijack_id, _target, **_kwargs: (
            ledger.load_record(hijack_id),
            None,
            None,
        ),
    )

    stop_calls: list[str] = []

    def stop_exact_monitor(
        record: MonitorRecord,
        *,
        expected_supervisor_identity: str,
        wait_for_supervisor_exit: bool,
    ) -> MonitorRecord:
        assert expected_supervisor_identity == "test-boot:71"
        assert wait_for_supervisor_exit is True
        stop_calls.append(record.monitor_id)
        terminal_meta = read_retention_meta(artifacts_dir)
        terminal_meta.update(
            {
                "monitor_state": "stopped",
                "monitor_exit_code": -15,
                "monitor_elapsed_seconds": 2.5,
                "stopped_at": "2026-11-16T20:00:00Z",
            }
        )
        write_retention_meta(artifacts_dir, terminal_meta)
        settlement = settle_claim_and_followup(
            artifacts_dir,
            terminal_meta,
            monitor_state="stopped",
            exit_code=-15,
            elapsed_seconds=2.5,
            capture=OutputCapture(),
            timeout_kind=None,
            project_name="proj",
            launch_followup=lambda *_args, **_kwargs: pytest.fail(
                "hijack settlement must suppress the automatic follow-up"
            ),
        )
        assert settlement.hijack_handled is True
        return replace(record, monitor_state="stopped", settled=True, exit_code=-15)

    result = stop_agent_for_hijack(
        target.name,
        deps=StopDeps(stop_monitor=stop_exact_monitor),
    )

    assert result.status == "held", f"{result!r}\nrecord={result.record!r}"
    assert result.record is not None
    assert result.record["scope"] == "monitor"
    assert result.record["state"] == "held"
    assert result.record["boundary"] == "monitor"
    assert result.record["boundary_outcome"] == "stopped"
    assert result.record["expected_claim_owner_pid"] == custody_pid
    assert stop_calls == [target.monitor_id]

    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pid == custody_pid
    assert claims[0].pinned is True

    done = json.loads(Path(artifacts_dir, "done.json").read_text(encoding="utf-8"))
    assert done["outcome"] == "hijacked"
    assert done["monitor_state"] == "stopped"
    assert done["boundary_outcome"] == "stopped"
    assert done["status_label"] == "Stopped"
    assert done["status_bucket"] == "Stopped"
    assert done["recovery"]["hijack_id"] == result.hijack_id

    suppressed = result.record["suppressed_followup"]
    assert suppressed["kind"] == "monitor_followup"
    descriptor = Path(suppressed["ref"])
    assert descriptor.is_file()
    payload = json.loads(descriptor.read_text(encoding="utf-8"))
    assert payload["command"] == "true"
    assert payload["execution_argv"] == ["/bin/true"]
    assert payload["followup"]["monitor_next_action"] == "Report the command result."
    assert "command_output" not in payload


def test_monitor_identity_mismatch_never_calls_stop_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack._stop_monitor import stop_monitor_target
    from tests.monitor._fixtures import record_from_disk

    repo = init_retention_repo(tmp_path / "workspace", dirty=False)
    artifacts_dir, project_file = make_retention_monitor(repo, monitor_state="running")
    meta = read_retention_meta(artifacts_dir)
    meta["monitor_supervisor_identity"] = "expected-identity"
    write_retention_meta(artifacts_dir, meta)
    target = _monitor_target(artifacts_dir, project_file, repo, meta)
    target.monitor_id = "different-monitor"
    record = MonitorRecord.from_record(record_from_disk(artifacts_dir))
    monkeypatch.setattr("sase.monitor.store.read_monitor_marker", lambda *_args: record)
    calls: list[str] = []

    def stop(*_args: Any, **_kwargs: Any) -> MonitorRecord:
        calls.append("stop")
        return record

    result = stop_monitor_target(target, deps=StopDeps(stop_monitor=stop))
    assert result.success is False
    assert result.identity_error is True
    assert calls == []


def test_terminal_monitor_checkpoint_replays_without_normal_followup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack import _stop_evidence, ledger
    from sase.axe import agent_meta as agent_meta_module
    from sase.axe import run_agent_exec_markers
    from sase.monitor.hijack_settlement import settle_monitor_hijack

    repo = init_retention_repo(tmp_path / "workspace", dirty=False)
    artifacts_dir, project_file = make_retention_monitor(repo, monitor_state="stopped")
    meta = read_retention_meta(artifacts_dir)
    meta.update(
        {
            "monitor_id": "retry-monitor",
            "monitor_supervisor_identity": "test-boot:91",
            "project_file": project_file,
            "project_name": "proj",
            "pid": os.getpid(),
        }
    )
    write_retention_meta(artifacts_dir, meta)
    from sase.agent._user_kill_intent import write_user_kill_intent

    intent = write_user_kill_intent(
        artifacts_dir,
        pid=os.getpid(),
        source="agent_hijack",
        mode="hijack",
        hijack_id="monitor-replay",
        custody_pid=os.getpid() + 200_001,
    )
    assert intent is not None
    record = ledger.new_requested_record(
        hijack_id="monitor-replay",
        agent_name=str(meta["name"]),
        artifacts_dir=artifacts_dir,
        pid=os.getpid(),
        project_file=project_file,
        workspace_num=3,
        workspace_dir=str(repo),
        expected_claim_owner_pid=os.getpid(),
        session="acme",
        target_key="monitor-replay-key",
        scope="monitor",
    )
    record = ledger.create_record(record)
    record = ledger.cas_advance_record(record, {"event": "begin_stop"})
    monkeypatch.setattr(
        agent_meta_module,
        "write_agent_meta_atomic",
        lambda path, value, **kwargs: _write_meta(str(path), dict(value), **kwargs),
    )
    monkeypatch.setattr(
        run_agent_exec_markers,
        "write_done_marker_and_update_index",
        lambda path, marker: Path(path, "done.json").write_text(
            json.dumps(marker), encoding="utf-8"
        ),
    )
    monkeypatch.setattr(
        _stop_evidence,
        "collect_and_attach_evidence",
        lambda hijack_id, _target, **_kwargs: (
            ledger.load_record(hijack_id),
            None,
            None,
        ),
    )

    first = settle_monitor_hijack(
        artifacts_dir, meta, monitor_state="stopped", project_name="proj"
    )
    assert first.settled is True, first
    descriptor_ref = ledger.load_record("monitor-replay")["suppressed_followup"]["ref"]
    second = settle_monitor_hijack(
        artifacts_dir, meta, monitor_state="stopped", project_name="proj"
    )

    assert first.settled is True
    assert second.settled is True
    assert ledger.load_record("monitor-replay")["state"] == "held"
    assert (
        ledger.load_record("monitor-replay")["suppressed_followup"]["ref"]
        == descriptor_ref
    )


def test_requested_monitor_intent_does_not_steal_terminal_race(
    tmp_path: Path,
) -> None:
    from sase.agent._user_kill_intent import write_user_kill_intent
    from sase.agent.hijack import ledger
    from sase.monitor.hijack_settlement import settle_monitor_hijack

    repo = init_retention_repo(tmp_path / "workspace", dirty=False)
    artifacts_dir, project_file = make_retention_monitor(repo, monitor_state="stopped")
    meta = read_retention_meta(artifacts_dir)
    write_retention_meta(artifacts_dir, meta)
    intent = write_user_kill_intent(
        artifacts_dir,
        pid=os.getpid(),
        source="agent_hijack",
        mode="hijack",
        hijack_id="monitor-requested-race",
        custody_pid=os.getpid(),
    )
    assert intent is not None
    record = ledger.new_requested_record(
        hijack_id="monitor-requested-race",
        agent_name=str(meta["name"]),
        artifacts_dir=artifacts_dir,
        pid=os.getpid(),
        project_file=project_file,
        workspace_num=3,
        workspace_dir=str(repo),
        expected_claim_owner_pid=os.getpid(),
        session="acme",
        target_key="monitor-requested-race-key",
        scope="monitor",
    )
    ledger.create_record(record)

    disposition = settle_monitor_hijack(
        artifacts_dir, meta, monitor_state="stopped", project_name="proj"
    )

    assert disposition.handled is False
    assert ledger.load_record("monitor-requested-race")["state"] == "requested"


def test_retrying_blocked_monitor_uses_monitor_settlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack import ledger
    from sase.agent.hijack._stop_orchestrator_common import HijackStopResult
    from sase.agent.hijack._stop_orchestrator_retry import retry_stop_blocked

    repo = init_retention_repo(tmp_path / "workspace", dirty=False)
    artifacts_dir, project_file = make_retention_monitor(repo, monitor_state="running")
    meta = read_retention_meta(artifacts_dir)
    meta["monitor_supervisor_identity"] = "test-boot:101"
    write_retention_meta(artifacts_dir, meta)
    target = _monitor_target(artifacts_dir, project_file, repo, meta)
    record = ledger.new_requested_record(
        hijack_id="monitor-retry",
        agent_name=target.name,
        artifacts_dir=artifacts_dir,
        pid=target.pid,
        project_file=project_file,
        workspace_num=3,
        workspace_dir=str(repo),
        expected_claim_owner_pid=target.claim_pid,
        session="acme",
        target_key="monitor-retry-key",
        scope="monitor",
    )
    record = ledger.create_record(record)
    record = ledger.cas_advance_record(record, {"event": "begin_stop"})
    record = ledger.cas_advance_record(
        record, {"event": "stop_blocked", "error": "still stopping"}
    )
    expected = HijackStopResult(
        status="held",
        message="repaired monitor",
        exit_code=0,
        hijack_id="monitor-retry",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_retry.terminate_with_retry",
        lambda *_args, **_kwargs: SimpleNamespace(
            success=True, monitor_record=SimpleNamespace(monitor_state="stopped")
        ),
    )

    def repair(*_args: Any, **_kwargs: Any) -> HijackStopResult:
        calls.append("monitor")
        return expected

    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_main.repair_monitor_settlement",
        repair,
    )
    result = retry_stop_blocked(
        target.name,
        record,
        subject=SimpleNamespace(occupant_name=target.name, occupant_reason="test"),
        target=target,
        reason=None,
        source="test",
        deps=StopDeps(),
    )

    assert result is expected
    assert calls == ["monitor"]
