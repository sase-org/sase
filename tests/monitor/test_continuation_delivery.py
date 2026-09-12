"""Ordinary continuation reservation, concurrent dispatch, and receiver adoption."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

import sase.monitor.followup as followup_module
import sase.procs.spawn as spawn_module
from sase.agent.launch_types import AgentLaunchResult
from sase.core.continuation_facade import transition_continuation_delivery
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.llm_provider.types import InvokeResult
from sase.monitor.continuation_admission import _continuation_admission_dir
from sase.monitor.continuation_delivery import (
    DELIVERY_ARTIFACTS_ENV,
    DELIVERY_CRASH_ENV,
    DELIVERY_IDENTITY_ENV,
    DELIVERY_KEY_ENV,
    _InjectedDeliveryCrash,
    adopt_ordinary_continuation_delivery,
    claim_ordinary_continuation_dispatch,
)
from sase.monitor.delivery import delivery_key, load_delivery_record
from sase.monitor.output import OutputCapture
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.procs.runtime import proc_started_path, write_json_atomic
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, write_project_file

_SETTLE_TIMEOUT = 2.0


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv(DELIVERY_CRASH_ENV, raising=False)


class _FakeSupervisorPid:
    pid = 4242424

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0


def _promote_and_start_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, dict[str, Any]]:
    write_project_file(
        "proj", running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())]
    )
    make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        llm_provider="anthropic",
        reasoning_effort="high",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
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
    record = start_monitor(
        StartMonitorRequest(
            command="true",
            reason="verify",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="acme",
            next_action="Report that it finished.",
        )
    )
    for path in Path(record.artifacts_dir).parent.iterdir():
        if path.is_dir() and path.name != Path(record.artifacts_dir).name:
            (path / "done.json").write_text("{}", encoding="utf-8")
    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    meta["stopped_at"] = "2026-08-12T14:19:48+00:00"
    return record.artifacts_dir, meta


def _capture(text: str = "hello world\n") -> OutputCapture:
    capture = OutputCapture()
    capture.append_bytes(text.encode())
    return capture


def _fake_result(**overrides: Any) -> AgentLaunchResult:
    defaults: dict[str, Any] = {
        "pid": 999999,
        "workspace_num": 3,
        "workspace_dir": "/tmp/whatever",
        "output_path": "/tmp/whatever.txt",
        "agent_name": "acme--1",
    }
    defaults.update(overrides)
    return AgentLaunchResult(**defaults)


def _launch(
    monitor_dir: str,
    meta: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    *,
    spawn: Any | None = None,
) -> tuple[Any, list[dict[str, Any]]]:
    captured: list[dict[str, Any]] = []

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.append(kwargs)
        if spawn is not None:
            return spawn(**kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)
    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=_capture(),
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )
    return result, captured


def test_followup_reserves_identity_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, meta = _promote_and_start_monitor(tmp_path, monkeypatch)
    result, captured = _launch(monitor_dir, meta, monkeypatch)

    assert result.launched is True
    assert len(captured) == 1
    env = captured[0]["extra_env"]
    assert env[DELIVERY_IDENTITY_ENV] == "acme--1"
    key = json.loads(env[DELIVERY_KEY_ENV])
    record = load_delivery_record(monitor_dir, key)
    assert record is not None
    assert record["disposition"] == "dispatching"
    assert record["reserved_identity"] == "acme--1"
    journal = _continuation_admission_dir(monitor_dir) / "journal.jsonl"
    assert journal.is_file()
    assert "acme--1" in journal.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("crash_at", "expected_disposition"),
    [
        ("before_reserve", None),
        ("after_reserve", "reserved"),
        ("before_spawn", "dispatching"),
        ("after_spawn", "dispatching"),
    ],
)
def test_injected_crashes_keep_delivery_key_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_at: str,
    expected_disposition: str | None,
) -> None:
    monitor_dir, meta = _promote_and_start_monitor(tmp_path, monkeypatch)
    monkeypatch.setenv(DELIVERY_CRASH_ENV, crash_at)
    with pytest.raises(_InjectedDeliveryCrash, match=crash_at):
        result, captured = _launch(monitor_dir, meta, monkeypatch)
        del result

    key = delivery_key(
        monitor_id=str(meta.get("monitor_id") or "monitor"),
        result_id=str(meta.get("continuation_monitor_result_id") or "result"),
        branch="completed",
    )
    record = load_delivery_record(monitor_dir, key)
    if expected_disposition is None:
        assert record is None
    else:
        assert record is not None
        assert record["disposition"] == expected_disposition
        assert record["reserved_identity"] == "acme--1"


def test_concurrent_dispatch_spawns_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, meta = _promote_and_start_monitor(tmp_path, monkeypatch)
    captured: list[dict[str, Any]] = []
    started = threading.Barrier(2)

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.append(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)
    results: list[Any] = []
    errors: list[BaseException] = []

    def worker() -> None:
        started.wait(timeout=5)
        try:
            results.append(
                followup_module.launch_followup_agent(
                    monitor_dir,
                    dict(meta),
                    monitor_state="completed",
                    exit_code=0,
                    elapsed_seconds=1.5,
                    capture=_capture(),
                    project_name="proj",
                    settle_timeout_seconds=_SETTLE_TIMEOUT,
                )
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(results) == 2
    assert all(item.launched for item in results)
    assert len(captured) == 1
    identities = {item.agent_name for item in results}
    assert identities == {"acme--1"}


def test_receiver_adopts_before_provider_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    claim = claim_ordinary_continuation_dispatch(
        str(artifacts),
        monitor_id="monitor-1",
        result_id="result-1",
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    assert claim.spawn is True
    monkeypatch.setenv(DELIVERY_ARTIFACTS_ENV, str(artifacts))
    monkeypatch.setenv(DELIVERY_KEY_ENV, json.dumps(claim.key, sort_keys=True))
    monkeypatch.setenv(DELIVERY_IDENTITY_ENV, "acme--1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme--1")

    adopted = adopt_ordinary_continuation_delivery()
    assert adopted is not None
    assert adopted["disposition"] == "acknowledged"
    assert adopted["acknowledged_by"] == "acme--1"

    again = adopt_ordinary_continuation_delivery()
    assert again is not None
    assert again["disposition"] == "acknowledged"

    with pytest.raises(ValueError, match="cannot allocate intruder--1"):
        adopt_ordinary_continuation_delivery(agent_name="intruder--1")


def test_invoke_adopts_before_fake_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.llm_provider._invoke import invoke_agent

    artifacts = tmp_path / "child"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    parent = tmp_path / "monitor"
    parent.mkdir()
    claim = claim_ordinary_continuation_dispatch(
        str(parent),
        monitor_id="monitor-1",
        result_id="result-1",
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    monkeypatch.setenv(DELIVERY_ARTIFACTS_ENV, str(parent))
    monkeypatch.setenv(DELIVERY_KEY_ENV, json.dumps(claim.key, sort_keys=True))
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
            artifacts_dir=str(artifacts),
            provider_name="fakey",
            suppress_output=True,
            skip_preprocessing=True,
        )

    provider.invoke.assert_called_once()
    record = load_delivery_record(parent, claim.key)
    assert record is not None
    assert record["disposition"] == "acknowledged"
    assert record["acknowledged_by"] == "acme--1"


def test_wrong_receiver_cannot_transition_delivery() -> None:
    from sase.monitor.delivery import new_delivery_record, transition_delivery

    record = new_delivery_record(
        {"monitor_id": "monitor-1", "result_id": "result-1", "branch": "failed"},
        selected_action="continue",
    )
    reserved = transition_delivery(record, "reserved", reserved_identity="acme--1")
    dispatching = transition_delivery(reserved, "dispatching")
    with pytest.raises(ValueError, match="intruder--1"):
        transition_delivery(dispatching, "acknowledged", acknowledged_by="intruder--1")
    acknowledged = transition_delivery(
        dispatching, "acknowledged", acknowledged_by="acme--1"
    )
    assert acknowledged["disposition"] == "acknowledged"


def test_illegal_skip_of_dispatching_is_rejected() -> None:
    from sase.monitor.delivery import new_delivery_record, transition_delivery

    record = new_delivery_record(
        {"monitor_id": "monitor-1", "result_id": "result-1", "branch": "failed"},
        selected_action="continue",
    )
    reserved = transition_delivery(record, "reserved", reserved_identity="acme--1")
    with pytest.raises(ValueError, match="dispatching"):
        transition_delivery(reserved, "acknowledged", acknowledged_by="acme--1")


def test_schema_version_used_by_transition_request() -> None:
    payload = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "record": {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "key": {
                "monitor_id": "monitor-1",
                "result_id": "result-1",
                "branch": "failed",
            },
            "selected_action": "continue",
            "attempt_history": [
                {
                    "attempt_id": "attempt-1",
                    "status": "pending",
                    "recorded_at": "2026-09-12T00:00:00Z",
                }
            ],
            "disposition": "pending",
        },
        "target": "cancelled",
        "recorded_at": "2026-09-12T00:00:01Z",
    }
    cancelled = transition_continuation_delivery(payload)
    assert cancelled["disposition"] == "cancelled"
