"""Manual monitor resume and terminal delivery recovery tests."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

import sase.monitor.followup as followup_module
import sase.monitor.outcome_policy as outcome_policy_module
import sase.monitor.resume as resume_module
import sase.procs.spawn as spawn_module
from sase.agent._family_attach_types import FamilyAttachLaunchPlan
from sase.agent.launch_types import AgentLaunchResult
from sase.continuation_capture._storage import continuation_root, sha_json
from sase.feature_flags import override_flags
from sase.llm_provider.types import InvokeResult
from sase.monitor.continuation_delivery import (
    DELIVERY_ARTIFACTS_ENV,
    DELIVERY_CRASH_ENV,
    DELIVERY_IDENTITY_ENV,
    DELIVERY_KEY_ENV,
    _InjectedDeliveryCrash,
    adopt_ordinary_continuation_delivery,
    claim_ordinary_continuation_dispatch,
)
from sase.monitor.delivery import (
    delivery_key,
    load_delivery_record,
    update_delivery_workspace,
)
from sase.monitor.models import MonitorRecord
from sase.monitor.resume import MonitorResumeError, resume_monitor
from sase.monitor.result_projection import build_monitor_result_wire
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.procs.runtime import proc_started_path, write_json_atomic
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, record_from_disk, write_project_file


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


class _FakeSupervisorPid:
    pid = 4242424

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0


def _terminal_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, MonitorRecord, dict[str, Any]]:
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )

    def fake_popen(*args: object, **kwargs: object) -> _FakeSupervisorPid:
        argv = args[0]
        assert isinstance(argv, list)
        proc_id = argv[argv.index("--proc-id") + 1]
        pass_fds = kwargs["pass_fds"]
        assert isinstance(pass_fds, tuple)
        pid_fd = pass_fds[0]
        assert isinstance(pid_fd, int)
        os.write(pid_fd, json.dumps({"pid": _FakeSupervisorPid.pid}).encode() + b"\n")
        write_json_atomic(proc_started_path(proc_id), {"pid": _FakeSupervisorPid.pid})
        return _FakeSupervisorPid()

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        outcome_policy_module,
        "freeze_start_outcome_policy",
        lambda *args, **kwargs: None,
    )
    starter = make_starter_agent(
        "proj",
        "20260912120000",
        "acme",
        agent_family="acme",
        workspace_num=3,
        workspace_dir=str(tmp_path),
        cl_name="acme",
    )

    def fake_resolve_plan(*args: object, **kwargs: object) -> FamilyAttachLaunchPlan:
        del args, kwargs
        return FamilyAttachLaunchPlan(
            parent_arg="acme",
            suffix_arg="@",
            parent_name="acme--0",
            parent_base="acme",
            parent_timestamp="20260912120000",
            parent_artifacts_dir=starter,
            role_suffix="--1",
            agent_name="acme--1",
            agent_family_role="code",
            parent_family_member_name="acme--0",
            parent_family_role_suffix="--0",
            parent_needs_rename=False,
            parent_project_name="proj",
            parent_is_running=False,
            parent_cl_name="acme",
            parent_workspace_dir=str(tmp_path),
            parent_workspace_num=3,
        )

    monkeypatch.setattr(
        followup_module, "resolve_family_attach_plan", fake_resolve_plan
    )

    started = start_monitor(
        StartMonitorRequest(
            command="just check",
            reason="verify",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            start_status="TESTING",
            stop_status="TESTED",
            lane="acme",
            next_action="fix the failure",
            next_output="auto",
            transfer_claim_from_pid=os.getpid(),
        )
    )
    (Path(starter) / "done.json").write_text(
        json.dumps({"outcome": "done", "name": "acme"}),
        encoding="utf-8",
    )
    monitor_dir = started.artifacts_dir
    meta_path = Path(monitor_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "monitor_state": "failed",
            "monitor_settled": True,
            "monitor_exit_code": 1,
            "monitor_elapsed_seconds": 60.0,
            "run_started_at": "2026-09-12T12:00:00+00:00",
            "stopped_at": "2026-09-12T12:01:00+00:00",
        }
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    monitor_id = str(meta["monitor_id"])
    (Path(monitor_dir) / "live_reply.md").write_text(
        "FAILED_SENTINEL\n",
        encoding="utf-8",
    )
    result = build_monitor_result_wire(
        monitor_id=monitor_id,
        monitor_state="failed",
        exit_code=1,
        command="just check",
        cwd=str(tmp_path),
        started_at="2026-09-12T12:00:00+00:00",
        stopped_at="2026-09-12T12:01:00+00:00",
        elapsed_seconds=60.0,
        timeout_seconds=30.0,
        starter_execution_id="20260912120000",
        workspace_identity=str(tmp_path),
        retained_log={
            "log_ref": "local:continuation/logs/abc123def456.txt",
            "total_observed_bytes": 16,
            "complete": True,
            "drain_confirmed": True,
        },
        result_seed_extra={"frozen": "sentinel"},
    )
    result_path = (
        continuation_root(monitor_dir)
        / "records"
        / "monitor_result"
        / f"{result['result_id']}.json"
    )
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    meta["continuation_monitor_result_id"] = result["result_id"]
    meta["continuation_monitor_result_path"] = str(result_path)
    meta["continuation_monitor_result_sha256"] = sha_json(result)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return monitor_dir, MonitorRecord.from_record(record_from_disk(monitor_dir)), meta


def _fake_spawn(captured: list[dict[str, Any]]) -> Any:
    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.append(kwargs)
        return AgentLaunchResult(
            pid=1111,
            workspace_num=3,
            workspace_dir="/tmp/work",
            output_path="/tmp/out.txt",
            agent_name="acme--1",
        )

    return fake_spawn


def test_resume_uses_the_frozen_result_delivery_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    result = resume_monitor(record)

    assert result.spawned is True
    assert result.agent_name == "acme--1"
    assert len(captured) == 1
    delivery_key_payload = json.loads(
        captured[0]["extra_env"]["SASE_MONITOR_DELIVERY_KEY"]
    )
    assert delivery_key_payload == {
        "monitor_id": record.monitor_id,
        "result_id": meta["continuation_monitor_result_id"],
        "branch": "failed",
    }
    record_payload = load_delivery_record(monitor_dir, delivery_key_payload)
    assert record_payload is not None
    assert record_payload["disposition"] == "dispatching"
    on_disk = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk["monitor_followup_agent"] == "acme--1"
    assert on_disk["monitor_followup_outcome"] == "launched"


def test_resume_uses_persisted_record_protocol_when_rollout_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    with override_flags(monitor_continuation_records=False):
        result = resume_monitor(record)

    assert result.spawned is True
    assert result.agent_name == "acme--1"
    delivery_key_payload = json.loads(
        captured[0]["extra_env"]["SASE_MONITOR_DELIVERY_KEY"]
    )
    assert delivery_key_payload == {
        "monitor_id": record.monitor_id,
        "result_id": meta["continuation_monitor_result_id"],
        "branch": "failed",
    }
    record_payload = load_delivery_record(monitor_dir, delivery_key_payload)
    assert record_payload is not None
    assert record_payload["disposition"] == "dispatching"


def test_resume_does_not_retry_dispatching_record_without_uninvoked_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    claim = claim_ordinary_continuation_dispatch(
        monitor_dir,
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    assert claim.record["disposition"] == "dispatching"
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    result = resume_monitor(record)

    assert result.spawned is False
    assert result.agent_name == "acme--1"
    assert result.ownership_outcome == "existing_receiver"
    assert captured == []
    payload = load_delivery_record(monitor_dir, claim.key)
    assert payload is not None
    assert payload["disposition"] == "dispatching"
    assert payload["reserved_identity"] == "acme--1"


def test_checkpoint_resume_creates_numbered_manual_branch_and_supersedes_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    base_key = delivery_key(
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
    )
    claim_ordinary_continuation_dispatch(
        monitor_dir,
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    checkpoint = tmp_path / "checkpoint.yml"
    checkpoint.write_text(
        "objective: recover safely\ncoverage: [abc]\n", encoding="utf-8"
    )
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    result = resume_monitor(
        record, checkpoint_path=str(checkpoint), model="codex/gpt-5"
    )

    assert result.manual_revision is True
    assert result.branch == "manual-recovery-1"
    assert len(captured) == 1
    old = load_delivery_record(monitor_dir, base_key)
    assert old is not None
    assert old["disposition"] == "needs_attention"
    manual_key = json.loads(captured[0]["extra_env"]["SASE_MONITOR_DELIVERY_KEY"])
    assert manual_key["branch"] == "manual-recovery-1"
    prompt = captured[0]["prompt"]
    assert "## Continuation checkpoint" in prompt
    assert "recover safely" in prompt
    assert '"coverage": [' in prompt
    assert "| **Outcome** | FAILED — exit 1 |" in prompt
    assert (
        Path(monitor_dir) / "continuation" / "manual_resume" / "manual-recovery-1.json"
    ).exists()
    on_disk = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk["continuation_intent_id"].endswith(
        on_disk["continuation_intent_id"].split(":")[-1]
    )
    assert on_disk["continuation_checkpoint_ref"].startswith("local:continuation/")


def test_resume_rejects_fire_and_forget_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, _meta = _terminal_monitor(tmp_path, monkeypatch)
    meta_path = Path(monitor_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text())
    meta.pop("monitor_next_action", None)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    record = MonitorRecord.from_record(record_from_disk(monitor_dir))

    with pytest.raises(MonitorResumeError, match="fire-and-forget"):
        resume_monitor(record)


def test_checkpoint_resume_preserves_concurrent_acknowledgment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    claim = claim_ordinary_continuation_dispatch(
        monitor_dir,
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    monkeypatch.setenv(DELIVERY_ARTIFACTS_ENV, monitor_dir)
    monkeypatch.setenv(DELIVERY_KEY_ENV, json.dumps(claim.key, sort_keys=True))
    monkeypatch.setenv(DELIVERY_IDENTITY_ENV, "acme--1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme--1")
    original = resume_module._apply_resume_adoption  # noqa: SLF001

    def adopt_then_apply(*args: Any, **kwargs: Any) -> Any:
        adopted = adopt_ordinary_continuation_delivery()
        assert adopted is not None
        assert adopted["disposition"] == "acknowledged"
        assert adopted["acknowledged_by"] == "acme--1"
        return original(*args, **kwargs)

    monkeypatch.setattr(resume_module, "_apply_resume_adoption", adopt_then_apply)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )
    checkpoint = tmp_path / "checkpoint.yml"
    checkpoint.write_text(
        "objective: recover safely\ncoverage: [abc]\n", encoding="utf-8"
    )

    with pytest.raises(MonitorResumeError, match="already been acknowledged"):
        resume_monitor(record, checkpoint_path=str(checkpoint), model="codex/gpt-5")

    old = load_delivery_record(monitor_dir, claim.key)
    assert old is not None
    assert old["disposition"] == "acknowledged"
    assert old["acknowledged_by"] == "acme--1"
    assert captured == []


def test_resume_refuses_stale_receiver_without_live_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    claim = claim_ordinary_continuation_dispatch(
        monitor_dir,
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    update_delivery_workspace(monitor_dir, claim.key, workspace_identity=str(tmp_path))
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    with pytest.raises(MonitorResumeError, match="ambiguous"):
        resume_monitor(record)

    payload = load_delivery_record(monitor_dir, claim.key)
    assert payload is not None
    assert payload["disposition"] == "needs_attention"
    assert payload.get("acknowledged_by") in {None, "acme--1"}
    assert captured == []


def test_concurrent_identical_checkpoint_resume_spawns_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _monitor_dir, record, _meta = _terminal_monitor(tmp_path, monkeypatch)
    checkpoint = tmp_path / "checkpoint.yml"
    checkpoint.write_text(
        "objective: recover safely\ncoverage: [abc]\n", encoding="utf-8"
    )
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )
    started = threading.Barrier(2)
    results: list[Any] = []
    errors: list[BaseException] = []

    def worker() -> None:
        started.wait(timeout=5)
        try:
            results.append(
                resume_monitor(
                    record, checkpoint_path=str(checkpoint), model="codex/gpt-5"
                )
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(captured) == 1
    assert results
    assert all(item.launched for item in results)
    assert {item.branch for item in results} <= {"manual-recovery-1"}
    assert all(
        isinstance(exc, MonitorResumeError) and exc.code == "ambiguous_receiver"
        for exc in errors
    )


def test_repeat_resume_after_acknowledgment_does_not_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )
    first = resume_monitor(record)
    assert first.spawned is True
    monkeypatch.setenv(DELIVERY_ARTIFACTS_ENV, monitor_dir)
    monkeypatch.setenv(
        DELIVERY_KEY_ENV,
        json.dumps(
            {
                "monitor_id": record.monitor_id,
                "result_id": meta["continuation_monitor_result_id"],
                "branch": "failed",
            },
            sort_keys=True,
        ),
    )
    monkeypatch.setenv(DELIVERY_IDENTITY_ENV, "acme--1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme--1")
    adopted = adopt_ordinary_continuation_delivery()
    assert adopted is not None
    assert adopted["disposition"] == "acknowledged"

    second = resume_monitor(record)

    assert second.spawned is False
    assert second.ownership_outcome == "already_delivered"
    assert len(captured) == 1
    payload = load_delivery_record(monitor_dir, adopted["key"])
    assert payload is not None
    assert payload["disposition"] == "acknowledged"
    assert payload["acknowledged_by"] == "acme--1"


def test_resume_then_adopt_invokes_provider_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider._invoke import invoke_agent

    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )
    launched = resume_monitor(record)
    assert launched.spawned is True
    assert len(captured) == 1
    child = tmp_path / "child"
    child.mkdir()
    (child / "agent_meta.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv(DELIVERY_ARTIFACTS_ENV, monitor_dir)
    monkeypatch.setenv(
        DELIVERY_KEY_ENV,
        json.dumps(
            {
                "monitor_id": record.monitor_id,
                "result_id": meta["continuation_monitor_result_id"],
                "branch": "failed",
            },
            sort_keys=True,
        ),
    )
    monkeypatch.setenv(DELIVERY_IDENTITY_ENV, "acme--1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme--1")
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="ok")
    provider.resolve_model_name.return_value = "fake-model"

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "sase.llm_provider._invoke.get_provider", lambda *a, **k: provider
        )
        patch.setattr("sase.llm_provider._invoke.postprocess_success", lambda **k: None)
        invoke_agent(
            "continue the work",
            agent_type="agent",
            artifacts_dir=str(child),
            provider_name="fakey",
            suppress_output=True,
            skip_preprocessing=True,
        )

    provider.invoke.assert_called_once()
    repeat = resume_monitor(record)
    assert repeat.spawned is False
    assert len(captured) == 1
    provider.invoke.assert_called_once()


def test_crash_after_fence_keeps_acknowledged_branch_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    base_key = delivery_key(
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
    )
    claim_ordinary_continuation_dispatch(
        monitor_dir,
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    checkpoint = tmp_path / "checkpoint.yml"
    checkpoint.write_text(
        "objective: recover safely\ncoverage: [abc]\n", encoding="utf-8"
    )
    monkeypatch.setenv(DELIVERY_CRASH_ENV, "after_resume_fence")

    with pytest.raises(_InjectedDeliveryCrash, match="after_resume_fence"):
        resume_monitor(record, checkpoint_path=str(checkpoint), model="codex/gpt-5")

    old = load_delivery_record(monitor_dir, base_key)
    assert old is not None
    assert old["disposition"] == "needs_attention"
    monkeypatch.delenv(DELIVERY_CRASH_ENV, raising=False)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )
    result = resume_monitor(
        record, checkpoint_path=str(checkpoint), model="codex/gpt-5"
    )
    assert result.spawned is True
    assert result.branch == "manual-recovery-1"
    assert len(captured) == 1
    old = load_delivery_record(monitor_dir, base_key)
    assert old is not None
    assert old["disposition"] == "needs_attention"


def test_resume_rejects_stopped_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _monitor_dir, record, _meta = _terminal_monitor(tmp_path, monkeypatch)
    record = replace(record, monitor_state="stopped")

    with pytest.raises(MonitorResumeError, match="inspection-only"):
        resume_monitor(record)
