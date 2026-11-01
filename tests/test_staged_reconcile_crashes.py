"""Kill the adopting process after real durable gate/monitor effects."""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import signal

import pytest

from sase.agent.staged_handoff import (
    read_adoption_receipt,
    read_staged_handoff,
    write_staged_handoff,
    write_staged_handoff_response,
)
from sase.axe.run_agent_exec_staged_recovery import recover_staged_handoff
from sase.axe.staged_handoff_reconcile import reconcile_staged_handoffs
from tests.test_staged_recovery_service import STAGED_ID, _settle_ok, _write_meta


def _crash_process(call) -> None:
    process = multiprocessing.get_context("fork").Process(target=call)
    process.start()
    process.join(timeout=30)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
        pytest.fail("adopter did not reach the durable crash boundary")
    assert process.exitcode == -signal.SIGKILL


def _kill(*_args, **_kwargs):
    os.kill(os.getpid(), signal.SIGKILL)


def test_gate_publication_survives_process_death_before_outer_receipt(
    tmp_path, monkeypatch, gate_home
):
    from sase.gate_turn import transaction
    from sase.gate_turn.staged_contract import prepare_staged_gate
    from sase.gate_turn.store import read_gate_turn_marker
    from sase.notifications.store import load_notifications
    from tests.gate_turn.test_publication_replay import (
        _custom_spec,
        _install_real_replay,
    )

    del gate_home
    creator = _install_real_replay(tmp_path, monkeypatch)
    monkeypatch.setenv("SASE_AGENT", "1")
    origin = Path(creator.artifacts_dir)
    prepared = prepare_staged_gate(
        _custom_spec("process-crash-gate"),
        creator={
            "project": "proj",
            "project_file": creator.project_file,
            "artifacts_dir": str(origin),
            "timestamp": creator.timestamp,
            "agent": "agent",
            "target": "agent",
            "meta": creator.meta,
        },
        artifacts_dir=str(origin),
        staged_id=STAGED_ID,
    )
    assert prepared.record is not None
    write_staged_handoff(prepared.record, artifacts_dir=str(origin))
    write_staged_handoff_response(
        STAGED_ID, "original response", artifacts_dir=str(origin)
    )
    _write_meta(origin, pid=999999)
    _settle_ok(monkeypatch)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner", lambda *_: "dead"
    )

    # Query the durable markers in both processes; an inherited in-memory
    # member map would hide the exact publication/receipt crash window.
    def find(_project, gate_id):
        for meta in (tmp_path / ".sase/projects").rglob("agent_meta.json"):
            record = read_gate_turn_marker("proj", str(meta.parent))
            if record is not None and record.gate_id == gate_id:
                return record
        return None

    monkeypatch.setattr(transaction, "find_gate_turn_by_gate_id", find)

    def adopt_and_die():
        import sase.axe.run_agent_exec_staged_recovery_adopt as adoption

        adoption.write_adopted_locked = _kill
        recover_staged_handoff(str(origin), mode="automatic")

    _crash_process(adopt_and_die)
    assert read_adoption_receipt(str(origin)) is None
    first = find("proj", "process-crash-gate")
    assert first is not None
    notifications = [item.id for item in load_notifications(include_dismissed=True)]
    assert len(notifications) == 1
    result = recover_staged_handoff(str(origin), mode="automatic")
    assert result.adopted
    assert result.destination["member_artifacts_dir"] == first.artifacts_dir
    assert [
        item.id for item in load_notifications(include_dismissed=True)
    ] == notifications
    assert recover_staged_handoff(str(origin), mode="automatic").already_adopted


def test_monitor_submit_survives_process_death_and_scheduler_reuses_proc(
    tmp_path, monkeypatch
):
    from sase.monitor.start_stage import stage_monitor
    from sase.procs.store import get_proc
    from tests.monitor._fixtures import wait_for_done
    from tests.monitor._start_stage import stage_env, stage_request

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    dirs = stage_env(tmp_path, monkeypatch)
    effect = tmp_path / "executions"
    staged = stage_monitor(stage_request(tmp_path, command=f"printf x >> {effect}"))
    dirs.append(staged.record.artifacts_dir)
    origin = Path(dirs[0])
    record = read_staged_handoff(str(origin))
    assert record is not None
    write_staged_handoff_response(
        record["staged_id"], "original response", artifacts_dir=str(origin)
    )
    # Preserve the starter's claim/model identity while supplying settled proof.
    original_meta = json.loads((origin / "agent_meta.json").read_text())
    _write_meta(origin, pid=999999)
    settled = json.loads((origin / "agent_meta.json").read_text())
    (origin / "agent_meta.json").write_text(
        json.dumps(
            {
                **settled,
                **original_meta,
                "finalizer_status": settled["finalizer_status"],
            }
        )
    )
    _settle_ok(monkeypatch)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner", lambda *_: "dead"
    )

    def submit_and_die():
        import sase.monitor.start_launch as launch

        submit = launch.submit_proc_request

        def crash_after_submit(*args, **kwargs):
            submit(*args, **kwargs)
            _kill()

        launch.submit_proc_request = crash_after_submit
        recover_staged_handoff(str(origin), mode="automatic")

    _crash_process(submit_and_die)
    assert read_adoption_receipt(str(origin)) is None
    wait_for_done(staged.record.artifacts_dir, timeout=30)
    proc = get_proc(staged.record.monitor_id)
    assert proc is not None
    assert effect.read_text() == "x"
    monkeypatch.setattr(
        "sase.monitor.start_launch.submit_proc_request",
        lambda *_a, **_k: pytest.fail("recovery submitted the command twice"),
    )
    summary = reconcile_staged_handoffs()
    assert summary.adopted == 1, summary
    assert reconcile_staged_handoffs().already_adopted == 1
    assert get_proc(staged.record.monitor_id).proc_id == proc.proc_id
    assert effect.read_text() == "x"
