"""Recovery of the receipt-before-inline-provider crash window for all kinds."""

import json
from pathlib import Path

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.agent.staged_handoff import (
    acquire_adoption_lock,
    build_questions_staged_record,
    read_adoption_receipt,
    read_staged_successor,
    successor_prompt_digest,
    write_adoption_receipt,
    write_staged_handoff,
    write_staged_handoff_response,
    write_staged_successor_locked,
    write_successor_prompt,
)
from sase.axe.staged_handoff_reconcile import reconcile_staged_handoffs
from tests.test_staged_recovery_service import (
    STAGED_ID,
    _record,
    _settle_ok,
    _write_meta,
)


@pytest.mark.parametrize("kind", ["pipe", "plan", "questions"])
@pytest.mark.parametrize("receipt_present", [False, True])
@pytest.mark.parametrize("interrupt", [None, "kill", "discard"])
def test_sweep_delivers_the_same_recorded_child_once(
    tmp_path, monkeypatch, kind, receipt_present, interrupt
):
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setenv("SASE_AGENT", "1")
    origin = tmp_path / ".sase/projects/proj/artifacts/ace-run/20261028120000"
    origin.mkdir(parents=True)
    project_file = tmp_path / "proj.sase"
    project_file.write_text("RUNNING:\n\nNAME: proj\nSTATUS: Ready\n", encoding="utf-8")
    stage = (
        build_questions_staged_record(
            questions=[{"question": "Continue?"}], staged_id=STAGED_ID
        )
        if kind == "questions"
        else _record(tmp_path, kind)
    )
    write_staged_handoff(stage, artifacts_dir=str(origin))
    write_staged_handoff_response(
        STAGED_ID, "original response", artifacts_dir=str(origin)
    )
    _write_meta(origin, pid=999999)
    _settle_ok(monkeypatch)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner", lambda *_: "dead"
    )
    child = origin.parent / "20261028120001"
    child.mkdir()
    launch_id = f"{STAGED_ID}:20261028120001"
    (child / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent--1",
                "staged_handoff_id": STAGED_ID,
                "staged_successor_launch_id": launch_id,
            }
        )
    )
    prompt = write_successor_prompt(origin, "continue the original task")
    successor = {
        "agent_name": "agent--1",
        "role_suffix": "--1",
        "artifacts_dir": str(child),
        "artifacts_timestamp": child.name,
        "launch_timestamp": child.name,
        "launch_identity": launch_id,
        "prompt_ref": str(prompt),
        "prompt_digest": successor_prompt_digest(prompt.read_text()),
        "project_name": "proj",
        "project_file": str(project_file),
        "origin_artifacts_timestamp": origin.name,
        "cl_name": "agent",
        "workspace_dir": str(origin.parent),
        "workspace_num": 1,
        "is_home_mode": False,
        "model": "model",
        "provider": "provider",
        "relationships": {},
        "continuation_refs": {},
        "loop_state": {},
    }
    with acquire_adoption_lock(origin):
        write_staged_successor_locked(
            {
                "schema_version": 1,
                "staged_id": STAGED_ID,
                "kind": kind,
                "origin_artifacts_dir": str(origin),
                "delivery_state": "created",
                "successor": successor,
            },
            artifacts_dir=origin,
        )
    if receipt_present:
        write_adoption_receipt(
            {
                "staged_id": STAGED_ID,
                "adopted_at": "2026-10-28T12:01:00Z",
                "outcome": "adopted",
                "refs": {"loop_outcome": None, "successor_artifacts_dir": str(child)},
            },
            artifacts_dir=str(origin),
        )
        # Successor-owned changes must not be checked as origin finalizer work.
        (origin / "finalizer_result.json").unlink()
    calls = []

    def spawn(**kwargs):
        calls.append(kwargs)
        (child / "done.json").write_text('{"outcome":"completed"}')
        return AgentLaunchResult(
            pid=123,
            workspace_num=1,
            workspace_dir=str(origin.parent),
            output_path=str(child / "output"),
        )

    monkeypatch.setattr("sase.agent.detached_child.spawn_detached_child", spawn)
    if interrupt:
        from sase.axe import run_agent_exec_staged_recovery_deliver as delivery

        real_deliver = delivery.deliver_staged_successor_detached

        def interrupt_before_lock(*args, **kwargs):
            if interrupt == "discard":
                (origin / ".sase_handoff_staged.json").unlink()
            else:
                meta = json.loads((origin / "agent_meta.json").read_text())
                meta["handoff_protocol"] = "killed"
                (origin / "agent_meta.json").write_text(json.dumps(meta))
            return real_deliver(*args, **kwargs)

        monkeypatch.setattr(
            delivery, "deliver_staged_successor_detached", interrupt_before_lock
        )
    first = reconcile_staged_handoffs()
    if interrupt:
        assert first.held == 1, first
        assert not calls
        assert (
            read_staged_successor(str(origin), staged_id=STAGED_ID)["delivery_state"]
            == "created"
        )
        return
    assert first.adopted + first.already_adopted == 1, first
    assert first.delivered == int(receipt_present)
    second = reconcile_staged_handoffs()
    assert second.already_adopted == 1 and not second.errors
    assert len(calls) == 1
    assert calls[0]["timestamp"] == child.name
    assert calls[0]["prompt"] == "continue the original task"
    assert read_adoption_receipt(str(origin))["outcome"] == "adopted"
    assert (
        read_staged_successor(str(origin), staged_id=STAGED_ID)["delivery_state"]
        == "terminal"
    )
