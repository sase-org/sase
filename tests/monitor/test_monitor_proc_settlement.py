"""Unit tests for proc-backed monitor settlement ordering."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.bead.epic_launch_handoff import (
    CompletionNotificationPayload,
    defer_epic_completion_until_monitor_settlement,
)
from sase.continuation_capture.rollout import (
    MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
)
from sase.monitor.followup import FollowupLaunchResult
from sase.monitor.proc_adapter import settle_monitor_artifacts, settle_monitor_followup
from sase.monitor.settlement import LOST_FOLLOWUP_ERROR
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, write_project_file

_STARTER_SCRATCH_KEY = "acme-ws3-20261020_100000"


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _make_proc_monitor(
    tmp_path: Path,
    *,
    next_action: str | None = "Report that it finished.",
) -> str:
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-monitor", "acme", pid=os.getpid())],
    )
    return make_starter_agent(
        "proj",
        "20260906120000",
        "acme--mon",
        agent_session="acme",
        agent_session_role="monitor",
        monitor_id="abc123def456",
        monitor_command="true",
        monitor_cwd=str(tmp_path),
        monitor_reason="test",
        monitor_stop_status="MONITORED",
        monitor_timeout_seconds=30.0,
        monitor_next_action=next_action,
        monitor_state="running",
        cl_name="acme",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        shell_kind="proc",
        monitor_continuation_protocol=MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
    )


def _settlement_state(artifacts_dir: str) -> dict[str, object]:
    return {
        "artifacts_dir": artifacts_dir,
        "proc_id": "abc123def456",
        "status": "success",
        "termination_reason": "success",
        "exit_code": 0,
    }


def _prepare_starter_scratch(
    artifacts_dir: str,
    tmp_path: Path,
    *,
    record_key: bool = True,
) -> tuple[Path, Path, Path]:
    managed_root = tmp_path / "managed"
    cargo = managed_root / "cargo-targets" / _STARTER_SCRATCH_KEY
    agent_tmp = managed_root / "agent-tmp" / _STARTER_SCRATCH_KEY
    cargo.mkdir(parents=True)
    agent_tmp.mkdir(parents=True)
    (cargo / "payload.txt").write_text("cargo", encoding="utf-8")
    (agent_tmp / "payload.txt").write_text("tmp", encoding="utf-8")
    starter_dir = make_starter_agent(
        "proj",
        "20260906115900",
        "acme",
        **({"launch_scratch_key": _STARTER_SCRATCH_KEY} if record_key else {}),
    )
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["monitor_starter_artifacts_dir"] = starter_dir
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return managed_root, cargo, agent_tmp


def _assert_followup_runs_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cargo: Path,
    agent_tmp: Path,
    expected_removed: bool,
) -> None:
    import sase.monitor.proc_adapter as proc_adapter

    def observe_cleanup(*_args: object, **_kwargs: object) -> SimpleNamespace:
        assert cargo.exists() is not expected_removed
        assert agent_tmp.is_dir()
        return SimpleNamespace(error=None, launch_result=None)

    monkeypatch.setattr(proc_adapter, "settle_claim_and_followup", observe_cleanup)


def test_settle_monitor_artifacts_leaves_stopped_at_unpersisted(
    tmp_path: Path,
) -> None:
    artifacts_dir = _make_proc_monitor(tmp_path)
    state = _settlement_state(artifacts_dir)

    settle_monitor_artifacts(state)

    on_disk = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert "stopped_at" not in on_disk
    assert on_disk["continuation_monitor_result_ref"].startswith(
        "local:continuation/records/monitor_result/"
    )
    assert Path(on_disk["continuation_monitor_result_path"]).exists()
    monitor_meta = state["monitor_meta"]
    assert isinstance(monitor_meta, dict)
    assert isinstance(monitor_meta.get("stopped_at"), str)
    assert (
        monitor_meta["continuation_monitor_result_id"]
        == on_disk["continuation_monitor_result_id"]
    )


def test_settle_monitor_followup_persists_stopped_at_after_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir = _make_proc_monitor(tmp_path)
    followup_dir = tmp_path / "followup"
    followup_dir.mkdir()
    state = _settlement_state(artifacts_dir)
    settle_monitor_artifacts(state)
    import sase.monitor.proc_adapter as proc_adapter

    wait_calls: list[tuple[str, int | None]] = []

    def fake_launch_success(
        _artifacts_dir: str, meta: dict[str, object], **_kwargs: object
    ) -> FollowupLaunchResult:
        on_disk = json.loads((Path(_artifacts_dir) / "agent_meta.json").read_text())
        assert "stopped_at" not in on_disk
        assert isinstance(meta.get("stopped_at"), str)
        meta["monitor_followup_agent"] = "acme--1"
        return FollowupLaunchResult(
            launched=True,
            agent_name="acme--1",
            artifacts_dir=str(followup_dir),
            pid=321,
        )

    def fake_wait(artifacts_dir_arg: str, pid: int | None) -> bool:
        on_disk = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
        assert "stopped_at" not in on_disk
        assert not (Path(artifacts_dir) / "done.json").exists()
        wait_calls.append((artifacts_dir_arg, pid))
        return True

    monkeypatch.setattr(proc_adapter, "launch_followup_agent", fake_launch_success)
    monkeypatch.setattr(proc_adapter, "wait_for_followup_started", fake_wait)

    settle_monitor_followup(state)

    on_disk = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert wait_calls == [(str(followup_dir), 321)]
    assert isinstance(on_disk.get("stopped_at"), str)
    assert on_disk["monitor_settled"] is True
    assert on_disk["monitor_followup_outcome"] == "launched"
    assert (Path(artifacts_dir) / "done.json").exists()


def test_settle_monitor_followup_sets_missing_stopped_at_on_resume(
    tmp_path: Path,
) -> None:
    artifacts_dir = _make_proc_monitor(tmp_path, next_action=None)
    state: dict[str, object] = {
        "artifacts_dir": artifacts_dir,
        "monitor_state": "completed",
        "monitor_exit_code": 0,
        "monitor_elapsed_seconds": 0.0,
        "response_path": "/tmp/response.md",
    }

    settle_monitor_followup(state)

    on_disk = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert isinstance(on_disk.get("stopped_at"), str)
    assert on_disk["monitor_settled"] is True
    assert (Path(artifacts_dir) / "done.json").exists()


def test_settle_monitor_followup_publishes_deferred_epic_completion_after_done(
    tmp_path: Path,
) -> None:
    root_dir = make_starter_agent(
        "proj",
        "20260906115900",
        "acme",
        cl_name="acme",
    )
    artifacts_dir = _make_proc_monitor(tmp_path, next_action=None)
    payload = CompletionNotificationPayload(
        sender="user-agent",
        cl_name="acme",
        success=True,
        notes=["planner completed"],
        action="JumpToAgent",
        action_data={"cl_name": "acme", "raw_suffix": Path(root_dir).name},
        extra_files=[],
        silent=False,
        tags=["done"],
    )
    assert defer_epic_completion_until_monitor_settlement(
        root_dir,
        artifacts_dir,
        payload,
    )
    state = _settlement_state(artifacts_dir)
    settle_monitor_artifacts(state)
    calls: list[dict[str, object]] = []

    def capture_notification(**kwargs: object) -> None:
        assert (Path(artifacts_dir) / "done.json").exists()
        on_disk = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
        assert on_disk["monitor_settled"] is True
        calls.append(kwargs)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "sase.notifications.senders.notify_workflow_complete",
            capture_notification,
        )
        settle_monitor_followup(state)
        settle_monitor_followup(state)

    assert len(calls) == 1
    action_data = calls[0]["action_data"]
    assert isinstance(action_data, dict)
    assert action_data["raw_suffix"] == Path(artifacts_dir).name
    assert action_data["agent_session_root_suffix"] == Path(root_dir).name
    assert action_data["agent_root_timestamp"] == Path(root_dir).name


def test_lost_followup_error_does_not_claim_a_reboot() -> None:
    assert "reboot" not in LOST_FOLLOWUP_ERROR.lower()
    assert "unknown" in LOST_FOLLOWUP_ERROR.lower()


def test_settle_monitor_artifacts_reuses_frozen_command_ended_at(
    tmp_path: Path,
) -> None:
    artifacts_dir = _make_proc_monitor(tmp_path)
    state = _settlement_state(artifacts_dir)
    state["command_ended_at"] = "2026-10-10T12:12:19Z"

    settle_monitor_artifacts(state)
    first_meta = state["monitor_meta"]
    assert isinstance(first_meta, dict)
    assert first_meta["stopped_at"] == "2026-10-10T12:12:19Z"
    first_id = first_meta["continuation_monitor_result_id"]

    settle_monitor_artifacts(state)
    second_meta = state["monitor_meta"]
    assert isinstance(second_meta, dict)
    assert second_meta["stopped_at"] == "2026-10-10T12:12:19Z"
    assert second_meta["continuation_monitor_result_id"] == first_id


def test_save_chat_history_failure_after_persist_raises_incident_import_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir = _make_proc_monitor(tmp_path)
    state = _settlement_state(artifacts_dir)
    state["command_ended_at"] = "2026-10-10T12:12:19Z"
    monkeypatch.setenv("SASE_PROC_SETTLEMENT_FAIL_SAVE_CHAT_HISTORY", "1")

    with pytest.raises(ImportError, match="legacy_" + "x" + "prompt_syntax_enabled"):
        settle_monitor_artifacts(state)

    on_disk = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert on_disk["continuation_monitor_result_id"].startswith("result:")
    result_path = Path(on_disk["continuation_monitor_result_path"])
    assert result_path.is_file()
    result = json.loads(result_path.read_text())
    assert result["outcome"] == "completed"
    assert result["exit_code"] == 0
    assert result["ended_at"] == "2026-10-10T12:12:19Z"


def test_settle_monitor_followup_reclaims_only_unheld_starter_cargo_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sase.axe.run_agent_runner_scratch as scratch

    artifacts_dir = _make_proc_monitor(tmp_path)
    managed_root, cargo, agent_tmp = _prepare_starter_scratch(artifacts_dir, tmp_path)
    monkeypatch.setattr(scratch, "managed_tmpdir_root", lambda: managed_root)
    _assert_followup_runs_after_cleanup(
        monkeypatch,
        cargo=cargo,
        agent_tmp=agent_tmp,
        expected_removed=True,
    )

    state = {
        "artifacts_dir": artifacts_dir,
        "proc_id": "abc123def456",
        "monitor_state": "completed",
        "monitor_exit_code": 0,
        "monitor_elapsed_seconds": 0.0,
    }
    settle_monitor_followup(state)

    assert not cargo.exists()
    assert agent_tmp.is_dir()
    cleanup_lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if "launch_scratch_cleanup" in line
    ]
    assert len(cleanup_lines) == 1
    assert cleanup_lines[0]["context"] == "monitor-settlement"
    assert cleanup_lines[0]["scratch_key"] == _STARTER_SCRATCH_KEY
    assert cleanup_lines[0]["status"] == "removed"

    settle_monitor_followup(state)

    assert not cargo.exists()
    assert agent_tmp.is_dir()
    cleanup_lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if "launch_scratch_cleanup" in line
    ]
    assert len(cleanup_lines) == 1
    assert cleanup_lines[0]["status"] == "skipped"
    assert cleanup_lines[0]["reason"] == "no-matching-candidates"


@pytest.mark.parametrize(
    ("observer", "live", "candidate_complete"),
    [("procfs", True, True), ("unobservable", False, False)],
)
def test_settle_monitor_followup_preserves_held_or_incompletely_observed_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    observer: str,
    live: bool,
    candidate_complete: bool,
) -> None:
    import sase.axe.run_agent_runner_scratch as scratch

    artifacts_dir = _make_proc_monitor(tmp_path)
    managed_root, cargo, agent_tmp = _prepare_starter_scratch(artifacts_dir, tmp_path)
    monkeypatch.setattr(scratch, "managed_tmpdir_root", lambda: managed_root)

    def observed(
        candidates: Iterable[tuple[str, Path]], **_kwargs: object
    ) -> SimpleNamespace:
        candidate_paths = list(candidates)
        return SimpleNamespace(
            observer=observer,
            candidates=[
                SimpleNamespace(live=live, complete=candidate_complete)
                for _candidate in candidate_paths
            ],
            diagnostics=(),
        )

    monkeypatch.setattr(scratch, "observe_launch_scratch_liveness", observed)
    _assert_followup_runs_after_cleanup(
        monkeypatch,
        cargo=cargo,
        agent_tmp=agent_tmp,
        expected_removed=False,
    )

    settle_monitor_followup(
        {
            "artifacts_dir": artifacts_dir,
            "proc_id": "abc123def456",
            "monitor_state": "completed",
            "monitor_exit_code": 0,
            "monitor_elapsed_seconds": 0.0,
        }
    )

    assert cargo.is_dir()
    assert agent_tmp.is_dir()


@pytest.mark.parametrize(
    "case",
    [
        "missing-key",
        "missing-dir",
        "missing-starter",
        "missing-starter-dir",
        "empty-starter",
        "invalid-starter",
        "monitor-only-key",
    ],
)
def test_settle_monitor_followup_noops_for_missing_key_or_cargo_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    import sase.axe.run_agent_runner_scratch as scratch

    artifacts_dir = _make_proc_monitor(tmp_path)
    managed_root, cargo, agent_tmp = _prepare_starter_scratch(
        artifacts_dir,
        tmp_path,
        record_key=case not in {"missing-key", "monitor-only-key"},
    )
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if case == "missing-starter":
        meta.pop("monitor_starter_artifacts_dir")
    elif case == "missing-starter-dir":
        meta["monitor_starter_artifacts_dir"] = str(tmp_path / "missing-starter")
    elif case == "empty-starter":
        meta["monitor_starter_artifacts_dir"] = ""
    elif case == "invalid-starter":
        meta["monitor_starter_artifacts_dir"] = 123
    elif case == "monitor-only-key":
        meta["launch_scratch_key"] = _STARTER_SCRATCH_KEY
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    if case == "missing-dir":
        import shutil

        shutil.rmtree(cargo)
    monkeypatch.setattr(scratch, "managed_tmpdir_root", lambda: managed_root)
    monkeypatch.setattr(
        scratch,
        "observe_launch_scratch_liveness",
        lambda *_args, **_kwargs: pytest.fail("missing scratch must not be observed"),
    )
    monkeypatch.setattr(
        scratch,
        "reap_managed_tmpdir",
        lambda *_args, **_kwargs: pytest.fail("missing scratch must not be reaped"),
    )

    def observe_cleanup(*_args: object, **_kwargs: object) -> SimpleNamespace:
        assert cargo.exists() is (case != "missing-dir")
        assert agent_tmp.is_dir()
        return SimpleNamespace(error=None, launch_result=None)

    import sase.monitor.proc_adapter as proc_adapter

    monkeypatch.setattr(proc_adapter, "settle_claim_and_followup", observe_cleanup)
    settle_monitor_followup(
        {
            "artifacts_dir": artifacts_dir,
            "proc_id": "abc123def456",
            "monitor_state": "completed",
            "monitor_exit_code": 0,
            "monitor_elapsed_seconds": 0.0,
        }
    )


def test_settle_monitor_followup_skips_joined_monitor_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.axe.run_agent_runner_scratch as scratch
    import sase.monitor.proc_adapter as proc_adapter

    artifacts_dir = _make_proc_monitor(tmp_path)
    managed_root, cargo, agent_tmp = _prepare_starter_scratch(artifacts_dir, tmp_path)
    monkeypatch.setattr(scratch, "managed_tmpdir_root", lambda: managed_root)
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["monitor_tool_run_joined"] = True
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setattr(
        scratch,
        "observe_launch_scratch_liveness",
        lambda *_args, **_kwargs: pytest.fail("joined monitors must be skipped"),
    )
    monkeypatch.setattr(
        scratch,
        "reap_managed_tmpdir",
        lambda *_args, **_kwargs: pytest.fail("joined monitors must be skipped"),
    )

    def observe_cleanup(*_args: object, **_kwargs: object) -> SimpleNamespace:
        assert cargo.is_dir()
        assert agent_tmp.is_dir()
        return SimpleNamespace(error=None, launch_result=None)

    monkeypatch.setattr(proc_adapter, "settle_claim_and_followup", observe_cleanup)
    settle_monitor_followup(
        {
            "artifacts_dir": artifacts_dir,
            "proc_id": "abc123def456",
            "monitor_state": "completed",
            "monitor_exit_code": 0,
            "monitor_elapsed_seconds": 0.0,
        }
    )
