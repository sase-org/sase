"""Tests for :mod:`sase.monitor.followup`."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import sase.monitor.followup as followup_module
import sase.procs.spawn as spawn_module
import sase.shells.followup as shells_followup_module
import sase.workspace_provider.store as workspace_store_module
from sase.agent.launch_types import AgentLaunchResult
from sase.continuation_capture import (
    persist_monitor_result,
    persist_monitor_result_best_effort,
)
from sase.continuation_capture.rollout import (
    MONITOR_CONTINUATION_PROTOCOL_FIELD,
    MONITOR_CONTINUATION_PROTOCOL_LEGACY,
    MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
)
from sase.core.artifact_file_facade import list_explicit_artifact_files
from sase.feature_flags import override_flags
from sase.llm_provider.continuation_budget import MONITOR_CONTINUATION_ENV
from sase.monitor.output import OutputCapture
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.procs.runtime import proc_started_path, write_json_atomic
from sase.running_field import WorkspaceClaim, WorkspaceClaimError

from ._fixtures import (
    make_starter_agent,
    register_workspace_checkout,
    write_project_file,
)

_SETTLE_TIMEOUT = 2.0


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


def _promote_and_start_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    settle_starter: bool = True,
    next_model: str | None = None,
) -> tuple[str, str, str]:
    """Return ``(monitor_dir, starter_dir, project_file)`` from a real promotion.

    Uses the real ``start_monitor()`` so the starter is genuinely promoted to
    a family root and the monitor member inherits real lineage, without
    actually spawning a detached supervisor subprocess.
    """
    project_file = write_project_file(
        "proj", running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())]
    )
    starter_dir = make_starter_agent(
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
        write_json_atomic(
            proc_started_path(proc_id),
            {"pid": _FakeSupervisorPid.pid},
        )
        return _FakeSupervisorPid()

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)
    request = StartMonitorRequest(
        command="true",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        start_status="MONITORING",
        stop_status="MONITORED",
        lane="acme",
        next_action="Report that it finished.",
        next_model=next_model,
    )
    record = start_monitor(request)
    if settle_starter:
        (Path(starter_dir) / "done.json").write_text("{}", encoding="utf-8")
    return record.artifacts_dir, starter_dir, project_file


def _capture_with_output(monitor_dir: str, text: str) -> OutputCapture:
    del monitor_dir
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


def test_launch_followup_agent_returns_false_without_a_next_action(
    tmp_path: Path,
) -> None:
    meta: dict[str, Any] = {"agent_family": "acme"}
    capture = _capture_with_output(str(tmp_path), "hi\n")

    result = followup_module.launch_followup_agent(
        str(tmp_path),
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        capture=capture,
        project_name="proj",
    )

    assert result.launched is False


def test_launch_followup_agent_attaches_to_the_lane_and_transfers_the_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    meta["stopped_at"] = "2026-08-12T14:19:48+00:00"
    capture = _capture_with_output(monitor_dir, "hello world\n")

    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    assert meta["monitor_followup_agent"] == "acme--1"
    assert "monitor_followup_error" not in meta

    assert captured["workspace_dir"] == str(tmp_path)
    assert captured["workspace_num"] == 3
    assert captured["retry_transfer_from_pid"] == os.getpid()
    # The starter's routing (set by `make_starter_agent()` above) is carried
    # onto the follow-up as %model:/%effort: prefix directives.
    assert captured["prompt"].startswith(
        "#fork:acme--0\n%model:claude-sonnet-5\n%effort:high\n\n"
    )

    env = captured["extra_env"]
    assert env["SASE_INTERNAL_AGENT_NAME_BYPASS"] == "1"
    assert env[MONITOR_CONTINUATION_ENV] == "1"
    plan = json.loads(env["SASE_AGENT_FAMILY_ATTACH"])
    assert plan["agent_name"] == "acme--1"
    assert plan["parent_base"] == "acme"
    # The starter's own role ("root") is inherited rather than the generic
    # numeric-suffix default ("feedback").
    assert plan["agent_family_role"] == "root"
    assert plan["parent_is_running"] is False

    # Persisted to disk too, not just the in-memory dict.
    on_disk = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk["monitor_followup_agent"] == "acme--1"


def test_launch_followup_agent_uses_legacy_launcher_when_records_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with override_flags(monitor_continuation_records=False):
        monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
            tmp_path, monkeypatch
        )
        meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
        assert (
            meta[MONITOR_CONTINUATION_PROTOCOL_FIELD]
            == MONITOR_CONTINUATION_PROTOCOL_LEGACY
        )
        meta["stopped_at"] = "2026-08-12T14:19:48+00:00"
        capture = _capture_with_output(monitor_dir, "hello world\n")

        captured: dict[str, Any] = {}

        def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
            captured.update(kwargs)
            return _fake_result()

        monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

        result = followup_module.launch_followup_agent(
            monitor_dir,
            meta,
            monitor_state="completed",
            exit_code=0,
            elapsed_seconds=1.5,
            capture=capture,
            project_name="proj",
            settle_timeout_seconds=_SETTLE_TIMEOUT,
        )

    assert result.launched is True
    assert meta["monitor_followup_agent"] == "acme--1"
    assert MONITOR_CONTINUATION_ENV not in captured["extra_env"]
    assert "continuation_monitor_result_id" not in meta
    assert not (Path(monitor_dir) / "continuation" / "delivery").exists()


def test_enabled_start_keeps_versioned_records_after_rollout_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert (
        meta[MONITOR_CONTINUATION_PROTOCOL_FIELD]
        == MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1
    )
    meta["stopped_at"] = "2026-08-12T14:19:48+00:00"
    capture = _capture_with_output(monitor_dir, "MUTABLE OUTPUT\n")
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    with override_flags(monitor_continuation_records=False):
        published = persist_monitor_result_best_effort(
            artifacts_dir=monitor_dir,
            meta=meta,
            monitor_state="failed",
            exit_code=1,
            elapsed_seconds=1.5,
            stopped_at=meta["stopped_at"],
            diagnostic_manifest=None,
            retained_log={
                "log_ref": "file:explicit:frozen-log",
                "local_locator": "diagnostics/retained_logs/frozen.log",
                "total_observed_bytes": 17,
                "retained_ranges": [{"start": 0, "end": 17}],
                "complete": True,
                "drain_confirmed": True,
            },
            project_name="proj",
            update_meta=False,
        )
        assert published is not None
        meta["monitor_command"] = "echo MUTABLE COMMAND"

        result = followup_module.launch_followup_agent(
            monitor_dir,
            meta,
            monitor_state="completed",
            exit_code=99,
            elapsed_seconds=999.0,
            capture=capture,
            project_name="proj",
            settle_timeout_seconds=_SETTLE_TIMEOUT,
        )

    assert result.launched is True
    assert captured["extra_env"][MONITOR_CONTINUATION_ENV] == "1"
    delivery_key = json.loads(captured["extra_env"]["SASE_MONITOR_DELIVERY_KEY"])
    assert delivery_key["result_id"] == published.result_id
    assert "| **Outcome** | FAILED — exit 1 |" in captured["prompt"]
    assert "MUTABLE" not in captured["prompt"]


def test_disabled_start_stays_legacy_after_rollout_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with override_flags(monitor_continuation_records=False):
        monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
            tmp_path, monkeypatch
        )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert (
        meta[MONITOR_CONTINUATION_PROTOCOL_FIELD]
        == MONITOR_CONTINUATION_PROTOCOL_LEGACY
    )
    meta["stopped_at"] = "2026-08-12T14:19:48+00:00"
    capture = _capture_with_output(monitor_dir, "hello world\n")
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    published = persist_monitor_result_best_effort(
        artifacts_dir=monitor_dir,
        meta=meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        stopped_at=meta["stopped_at"],
        diagnostic_manifest=None,
        retained_log={
            "log_ref": "file:explicit:legacy-log",
            "local_locator": "diagnostics/retained_logs/legacy.log",
            "total_observed_bytes": 12,
            "retained_ranges": [{"start": 0, "end": 12}],
            "complete": True,
            "drain_confirmed": True,
        },
        project_name="proj",
        update_meta=False,
    )
    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert published is None
    assert result.launched is True
    assert MONITOR_CONTINUATION_ENV not in captured["extra_env"]
    assert "SASE_MONITOR_DELIVERY_KEY" not in captured["extra_env"]
    assert "continuation_monitor_result_id" not in meta
    assert not (Path(monitor_dir) / "continuation" / "delivery").exists()


def test_launch_followup_agent_uses_explicit_next_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch, next_model="@small"
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert meta["monitor_next_model"] == "@small"
    capture = _capture_with_output(monitor_dir, "hello world\n")
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    assert captured["prompt"].startswith("#fork:acme--0\n%model:@small\n\n")
    assert "%effort:high" not in captured["prompt"]
    assert "%model:claude-sonnet-5" not in captured["prompt"]


def test_launch_followup_agent_renders_from_frozen_result_and_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    meta["stopped_at"] = "2026-08-12T14:19:48+00:00"
    meta["monitor_next_output"] = "none"
    persist_monitor_result(
        artifacts_dir=monitor_dir,
        meta=meta,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=1.5,
        stopped_at=meta["stopped_at"],
        diagnostic_manifest=None,
        retained_log={
            "log_ref": "file:explicit:frozen-log",
            "local_locator": "diagnostics/retained_logs/frozen.log",
            "total_observed_bytes": 17,
            "retained_ranges": [{"start": 0, "end": 17}],
            "complete": True,
            "drain_confirmed": True,
        },
        project_name="proj",
        update_meta=False,
    )
    frozen_result_id = meta["continuation_monitor_result_id"]
    meta["monitor_command"] = "echo MUTABLE COMMAND"
    meta["monitor_cwd"] = "/tmp/mutable-cwd"
    meta["monitor_next_action"] = "MUTABLE NEXT ACTION"
    capture = _capture_with_output(monitor_dir, "MUTABLE OUTPUT\n")
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=99,
        elapsed_seconds=999.0,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    prompt = captured["prompt"]
    assert result.launched is True
    assert "| **Outcome** | FAILED — exit 1 |" in prompt
    assert "```text\ntrue\n```" in prompt
    assert str(tmp_path) in prompt
    assert "Report that it finished." in prompt
    assert "MUTABLE" not in prompt
    delivery_key = json.loads(captured["extra_env"]["SASE_MONITOR_DELIVERY_KEY"])
    assert delivery_key["result_id"] == frozen_result_id


def test_launch_followup_agent_repairs_a_meta_workspace_num_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """meta["workspace_num"] can still read ``0`` while the monitor's cwd is a
    numbered directory (the monitor-claim defect this epic tracks separately);
    the follow-up must repair the pair via the registry lookup instead of
    defaulting to ``0`` and squatting in the numbered directory unclaimed."""
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    meta["workspace_num"] = 0
    capture = _capture_with_output(monitor_dir, "hello world\n")

    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)
    monkeypatch.setattr(
        shells_followup_module,
        "_workspace_dir_for_num",
        lambda project_name, workspace_num: str(tmp_path / "primary"),
    )
    monkeypatch.setattr(
        shells_followup_module,
        "resolve_consistent_workspace_pair",
        lambda primary_dir, workspace_dir, workspace_num: (workspace_dir, 3),
    )

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    assert result.degraded_reason is None
    # Repaired to the real number the directory maps to -- never 0 paired
    # with the numbered directory.
    assert captured["workspace_dir"] == str(tmp_path)
    assert captured["workspace_num"] == 3


def test_launch_followup_agent_repairs_a_nested_managed_dir_to_its_owning_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A monitor cwd nested inside a managed checkout -- not just the
    checkout root -- must repair via the real registry containment lookup
    to that checkout's workspace instead of degrading to workspace #0 (plan
    ``202609/monitor_nested_cwd_workspace_resolution.md``)."""
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    # ``_promote_and_start_monitor`` patches the global ``subprocess.Popen``
    # to a supervisor-argv-only fake; keep the real workspace-registry
    # lookups below from tripping it via their own ``git remote -v`` probe.
    monkeypatch.setattr(
        workspace_store_module, "_list_git_remote_urls", lambda primary_dir: []
    )
    primary = tmp_path / "primary"
    primary.mkdir()
    workspace_dir = register_workspace_checkout(primary, 7)
    nested = Path(workspace_dir) / "sase" / "repos" / "external" / "gh" / "x"
    nested.mkdir(parents=True)

    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    meta["workspace_num"] = 0
    meta["workspace_dir"] = str(nested)
    capture = _capture_with_output(monitor_dir, "hello world\n")

    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result(workspace_num=7, workspace_dir=workspace_dir)

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)
    monkeypatch.setattr(
        shells_followup_module,
        "_workspace_dir_for_num",
        lambda project_name, workspace_num: str(primary),
    )

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    assert result.degraded_reason is None
    # Repaired to the checkout root that owns the nested dir -- never left
    # squatting in the nested dir itself or degraded to #0.
    assert captured["workspace_dir"] == workspace_dir
    assert captured["workspace_num"] == 7


def test_launch_followup_agent_falls_back_to_primary_when_meta_pairing_is_unresolvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    meta["workspace_num"] = 0
    capture = _capture_with_output(monitor_dir, "hello world\n")
    primary = tmp_path / "primary"
    primary.mkdir()

    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result(workspace_num=0, workspace_dir=str(primary))

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)
    monkeypatch.setattr(
        shells_followup_module,
        "_workspace_dir_for_num",
        lambda project_name, workspace_num: str(primary),
    )
    monkeypatch.setattr(
        shells_followup_module,
        "resolve_consistent_workspace_pair",
        lambda primary_dir, workspace_dir, workspace_num: None,
    )

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    assert result.degraded_reason is not None
    assert "workspace #0" in result.degraded_reason
    assert str(primary) in result.degraded_reason
    # Never squats in the numbered directory with a 0 claim: both the spawn
    # call and the prompt name the primary checkout.
    assert captured["workspace_dir"] == str(primary)
    assert captured["workspace_num"] == 0
    assert "## Follow-up workspace" in captured["prompt"]
    assert str(primary) in captured["prompt"]


def test_launch_followup_agent_falls_back_to_fresh_claim_after_transfer_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    capture = _capture_with_output(monitor_dir, "hello world\n")
    calls: list[dict[str, Any]] = []

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        calls.append(kwargs)
        if len(calls) == 1:
            raise WorkspaceClaimError(
                "workspace #3 with pid 4242424 was not found",
                workspace_num=3,
            )
        return _fake_result(agent_name="acme--1")

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
        transfer_from_pid=4_242_424,
    )

    assert result.launched is True
    assert result.degraded_reason is not None
    assert "fresh claim on the same workspace" in result.degraded_reason
    assert len(calls) == 2
    assert calls[0]["retry_transfer_from_pid"] == 4_242_424
    assert calls[1]["retry_transfer_from_pid"] is None
    assert calls[1]["workspace_num"] == 3
    assert "## Follow-up workspace" in calls[1]["prompt"]
    assert "fresh claim on the same workspace" in calls[1]["prompt"]
    on_disk = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk["monitor_followup_degraded_reason"] == result.degraded_reason


def test_launch_followup_agent_falls_back_to_workspace_zero_when_workspace_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    capture = _capture_with_output(monitor_dir, "hello world\n")
    primary = tmp_path / "primary"
    primary.mkdir()
    calls: list[dict[str, Any]] = []

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        calls.append(kwargs)
        if len(calls) < 3:
            raise WorkspaceClaimError(
                "workspace #3 is already claimed",
                workspace_num=3,
            )
        return _fake_result(
            agent_name="acme--1",
            workspace_num=kwargs["workspace_num"],
            workspace_dir=kwargs["workspace_dir"],
        )

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)
    monkeypatch.setattr(
        shells_followup_module,
        "_workspace_dir_for_num",
        lambda project_name, workspace_num: str(primary),
    )

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
        transfer_from_pid=4_242_424,
    )

    assert result.launched is True
    assert result.degraded_reason is not None
    assert "workspace #0" in result.degraded_reason
    assert [call["workspace_num"] for call in calls] == [3, 3, 0]
    assert calls[2]["workspace_dir"] == str(primary)
    assert calls[2]["retry_transfer_from_pid"] is None
    assert "workspace #0" in calls[2]["prompt"]
    assert "Do not assume" in calls[2]["prompt"]
    env = calls[2]["extra_env"]
    plan = json.loads(env["SASE_AGENT_FAMILY_ATTACH"])
    assert plan["parent_workspace_num"] == 0
    assert plan["parent_workspace_dir"] == str(primary)


def test_launch_followup_agent_omits_the_fork_prefix_when_the_starter_never_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch, settle_starter=False
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    capture = _capture_with_output(monitor_dir, "hello\n")

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        followup_module,
        "spawn_agent_subprocess",
        lambda **kwargs: (captured.update(kwargs), _fake_result())[1],
    )

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=0.2,
    )

    assert result.launched is True
    assert "#fork:" not in captured["prompt"]
    # No #fork prefix, but the starter's routing still carries over.
    assert captured["prompt"].startswith("%model:claude-sonnet-5\n%effort:high\n\n")
    assert "# Monitored command finished" in captured["prompt"]


def test_launch_followup_agent_records_the_error_and_returns_false_on_failure(
    tmp_path: Path,
) -> None:
    # No promotion, no real family in the artifact index: resolution fails.
    write_project_file("proj")
    monitor_dir = str(tmp_path / "monitor-member")
    Path(monitor_dir).mkdir()
    meta: dict[str, Any] = {
        "agent_family": "acme",
        "monitor_next_action": "Report that it finished.",
        "monitor_command": "true",
        "monitor_id": "abc123def456",
    }
    (Path(monitor_dir) / "agent_meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )
    capture = _capture_with_output(monitor_dir, "hi\n")

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=0.2,
    )

    assert result.launched is False
    assert meta["monitor_followup_error"]
    assert "follow-up prompt saved to" in meta["monitor_followup_error"]
    prompt_path = Path(result.prompt_path or "")
    assert prompt_path.name == "monitor_followup_prompt.md"
    persisted_prompt = prompt_path.read_text(encoding="utf-8")
    assert "Report that it finished." in persisted_prompt
    assert persisted_prompt.endswith("%xprompts_enabled:true")
    artifacts = list_explicit_artifact_files(Path(monitor_dir))
    assert [artifact.label for artifact in artifacts] == [
        "Unlaunched monitor follow-up prompt"
    ]
    on_disk = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk["monitor_followup_error"] == meta["monitor_followup_error"]
    assert on_disk["monitor_followup_prompt_path"] == str(prompt_path)
