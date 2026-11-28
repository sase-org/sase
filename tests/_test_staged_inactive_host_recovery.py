"""Readopt, reserved tool-run, and staged-join cases for inactive settlement."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.staged_handoff import STAGED_HANDOFF_FILENAME
from tests._staged_inactive_host_helpers import (
    FAILED_AT,
    MONITOR_ID,
    NOW,
    STAGED_ID,
    artifact_dir,
    patch_owner_home,
    write_held_receipt,
    write_member_launch,
    write_monitor_stage,
    write_origin_meta,
    write_owner_index,
)


def test_readopt_invalidates_settlement_exactly_once(monkeypatch, tmp_path) -> None:
    import os
    from types import SimpleNamespace

    from sase.agent._staged_handoff_inactive import _read_inactive_settlement
    from sase.agent._staged_handoff_store import StagedHandoffError
    from sase.agent.staged_handoff import (
        read_adoption_receipt,
        write_staged_handoff_response,
    )
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )
    from sase.axe.run_agent_exec_staged_recovery import recover_staged_handoff
    from sase.core.tool_run import tool_run_show
    from sase.monitor.start_stage import stage_monitor
    from tests.monitor._start_stage import sandbox_project, stage_env, stage_request

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    root = sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    staged = stage_monitor(
        stage_request(
            tmp_path,
            command="just check",
            cwd=str(root),
            profile="verify",
        )
    )
    dirs.append(staged.record.artifacts_dir)
    origin = Path(dirs[0])
    member = Path(staged.record.artifacts_dir)
    staged_id = staged.staged_id
    first_run_id = staged.record.tool_run_id
    assert staged_id
    assert first_run_id
    write_held_receipt(origin, staged_id=staged_id)
    (origin / "done.json").write_text(
        json.dumps({"outcome": "failed", "finished_at": FAILED_AT}),
        encoding="utf-8",
    )
    settlement = _settle_inactive_staged_handoff(str(origin))
    assert settlement.settled is True
    assert settlement.cleanup_complete is True
    assert settlement.settled_tool_run_id == first_run_id
    shown = tool_run_show(first_run_id)["run"]
    assert shown["state"] == "signaled"
    assert any(
        "command was not run" in str(line) for line in (shown.get("diagnostics") or [])
    )
    assert _read_inactive_settlement(str(origin)) is not None
    handoff = json.loads((origin / STAGED_HANDOFF_FILENAME).read_text(encoding="utf-8"))
    assert handoff["payload"]["member_artifacts_dir"] == str(member)

    write_staged_handoff_response(
        staged_id, "monitor response", artifacts_dir=str(origin)
    )
    meta = json.loads((origin / "agent_meta.json").read_text(encoding="utf-8"))
    meta["pid"] = 999999
    meta["finalizer_status"] = {
        "phase": "settled",
        "status": "success",
        "run_id": "controller-run-1",
        "plan_digest": "digest-1",
        "started_at": NOW,
    }
    (origin / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (origin / "finalizer_result.json").write_text(
        json.dumps({"status": "success", "instances": []}), encoding="utf-8"
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery_facts.finalizer_settlement_refusal",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner",
        lambda *_args, **_kwargs: "dead",
    )
    submits: list[str] = []
    fake_pid = os.getpid() + 10000

    def _fake_submit(
        *args: Any, after_spawn: Any, after_ack: Any, **kwargs: Any
    ) -> Any:
        del args, kwargs
        submits.append("submit")
        after_spawn(SimpleNamespace(pid=fake_pid))
        proc = SimpleNamespace(pid=fake_pid, supervisor_id="supervisor-fake")
        after_ack(proc)
        return proc

    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _fake_submit)
    monkeypatch.setattr(
        "sase.monitor.start_launch.claim_monitor_workspace",
        lambda *args, **kwargs: SimpleNamespace(
            result=SimpleNamespace(success=True), starter_claim=None
        ),
    )
    result = recover_staged_handoff(str(origin), mode="explicit")
    assert result.adopted is True
    assert result.already_adopted is False
    assert result.kind == "monitor"
    assert result.destination is not None
    assert result.destination.get("member_artifacts_dir") == str(member)
    assert _read_inactive_settlement(str(origin)) is None
    assert submits == ["submit"]
    assert result.destination.get("monitor_id") == staged.record.monitor_id
    meta_after = json.loads((member / "agent_meta.json").read_text(encoding="utf-8"))
    recovered_run = meta_after.get("monitor_tool_run_id")
    assert recovered_run
    assert recovered_run != first_run_id
    assert tool_run_show(recovered_run)["run"]["state"] == "created"

    replay = recover_staged_handoff(str(origin), mode="explicit")
    assert replay.adopted is True
    assert replay.already_adopted is True
    assert submits == ["submit"]
    with pytest.raises(StagedHandoffError):
        write_held_receipt(origin, staged_id=staged_id)
    assert read_adoption_receipt(str(origin))["outcome"] == "adopted"


def test_settlement_settles_reserved_tool_run_as_never_executed(
    tmp_path, monkeypatch
) -> None:
    import os

    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )
    from sase.core.tool_run import (
        tool_run_reserve_staged_join,
        tool_run_show,
    )
    from sase.tool.handoff import reserve_handoff_run
    from sase.tool.argv import resolve_run_argv

    origin = artifact_dir(tmp_path, "sase-1.2")
    member = artifact_dir(tmp_path, "sase-1.2--mon")
    write_monitor_stage(origin)
    write_held_receipt(origin)
    write_origin_meta(origin, "sase-1.2")
    reservation = reserve_handoff_run(
        resolve_run_argv(["--", "true"]),
        owner_kind="proc",
        owner_id="proc-inactive-contracts",
        agent="sase-1.2--mon",
        starter={
            "agent": "sase-1.2--mon",
            "pid": os.getpid(),
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:1",
        },
    )
    assert reservation.reserved, reservation.error
    run_id = reservation.run_id
    patch_owner_home(monkeypatch, tmp_path / ".sase")
    write_member_launch(member, origin, tool_run_id=run_id)
    write_owner_index(member, origin)
    settlement = _settle_inactive_staged_handoff(str(origin))
    assert settlement.settled is True
    assert settlement.settled_tool_run_id == run_id
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] == "signaled"
    assert shown["terminal_cause"] == "stop_requested"
    assert any(
        "command was not run" in str(line) for line in (shown.get("diagnostics") or [])
    )


def test_settlement_releases_staged_join_reservation(tmp_path, monkeypatch) -> None:
    import os

    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )
    from sase.core.tool_run import (
        tool_run_reserve_staged_join,
        tool_run_show,
    )
    from sase.tool.handoff import reserve_handoff_run
    from sase.tool.argv import resolve_run_argv

    origin = artifact_dir(tmp_path, "sase-1.2")
    member = artifact_dir(tmp_path, "sase-1.2--mon")
    write_monitor_stage(origin)
    write_held_receipt(origin)
    write_origin_meta(origin, "sase-1.2")
    reservation = reserve_handoff_run(
        resolve_run_argv(["--", "true"]),
        owner_kind="proc",
        owner_id="proc-inactive-contracts",
        agent="sase-1.2--mon",
        starter={
            "agent": "sase-1.2--mon",
            "pid": os.getpid(),
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:1",
        },
    )
    assert reservation.reserved, reservation.error
    run_id = reservation.run_id
    tool_run_reserve_staged_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "staged_id": STAGED_ID,
            "monitor_id": MONITOR_ID,
            "agent": "sase-1.2--mon",
        }
    )
    patch_owner_home(monkeypatch, tmp_path / ".sase")
    write_member_launch(member, origin, tool_run_id=run_id, join_mode="staged")
    (member / "agent_meta.json").write_text(
        json.dumps({"monitor_id": MONITOR_ID, "monitor_staged_id": STAGED_ID}),
        encoding="utf-8",
    )
    write_owner_index(member, origin)
    settlement = _settle_inactive_staged_handoff(str(origin))
    assert settlement.settled is True
    assert settlement.released_join is True
    assert settlement.settled_tool_run_id is None
    assert tool_run_show(run_id)["run"]["state"] not in {"signaled"}
