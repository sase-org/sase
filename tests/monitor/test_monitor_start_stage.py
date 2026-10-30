"""Internal stage/adopt/cleanup transaction for monitor starts.

Public CLI stays on the immediate path. These tests call the staging
entries directly and keep existing ``start_monitor`` behavior unchanged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from sase.agent.staged_handoff import STAGED_HANDOFF_FILENAME, read_staged_handoff
from sase.core.staged_handoff import staged_monitor_launch_payload_schema_version
from sase.core.tool_run import tool_run_show
from sase.monitor.models import MonitorAlreadyRunningError, MonitorError
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.monitor.start_stage import (
    cleanup_staged_monitor,
    launch_from_persisted_payload,
    load_staged_monitor_launch_payload,
    stage_monitor,
)
from sase.monitor.staged_owner import launch_payload_path
from sase.procs.submission import ProcSubmitError
from sase.running_field import WorkspaceClaim
from sase.tool.owner import observe_owner_fact
from tests.monitor._fixtures import (
    make_starter_agent,
    patch_project_records,
    record_from_disk,
    register_workspace_checkout,
    wait_for_done,
    write_project_file,
)
from tests.monitor._join_helpers import reserve_detached_run


SANDBOX_CATALOG = """\
tools:
  check:
    argv: ["true"]
    description: sandbox verify probe
    stages: none
    inputs: []
    env: []
    args: deny
    fingerprint:
      repos: []
      toolchain: {}
"""


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_NATIVE_HELPER", raising=False)
    monkeypatch.delenv("SASE_FINALIZER_OWNED_TURN", raising=False)


def _sandbox_project(tmp_path: Path, name: str = "proj") -> Path:
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    sase_dir = root / "sase"
    sase_dir.mkdir(parents=True)
    (sase_dir / "sase.yml").write_text(SANDBOX_CATALOG, encoding="utf-8")
    return root


def _request(
    tmp_path: Path,
    *,
    command: str = "true",
    cwd: str | None = None,
    join_run_id: str | None = None,
    profile: str | None = None,
) -> StartMonitorRequest:
    return StartMonitorRequest(
        command=command,
        reason="verify staging",
        timeout_seconds=30.0,
        cwd=cwd or str(tmp_path),
        project_name="proj",
        start_status="MONITORING",
        stop_status="MONITORED",
        lane="acme",
        join_run_id=join_run_id,
        profile=profile,
    )


def _stage_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cwd: str | None = None,
    workspace_num: int = 3,
    workspace_dir: str | None = None,
    starter_workspace_dir: str | None = None,
) -> list[str]:
    write_project_file(
        "proj",
        workspace_dir=workspace_dir,
        running_claims=[
            WorkspaceClaim(workspace_num, "ace-run", "acme", pid=os.getpid())
        ],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=starter_workspace_dir or workspace_dir or cwd or str(tmp_path),
        workspace_num=workspace_num,
        pid=os.getpid(),
        cl_name="acme",
        agent_session="acme",
    )
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", starter_dir)
    dirs = [starter_dir]
    patch_project_records(monkeypatch, dirs)
    return dirs


def test_stage_persists_payload_and_reconstructs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)

    assert staged.replayed is False
    assert staged.record.monitor_state == "staged"
    assert staged.record.pid is None
    payload_path = launch_payload_path(staged.record.artifacts_dir)
    assert payload_path.is_file()
    loaded = load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    assert loaded["schema_version"] == staged_monitor_launch_payload_schema_version()
    assert loaded["staged_id"] == staged.staged_id
    assert loaded["monitor_id"] == staged.record.monitor_id
    assert loaded["cwd"] == str(tmp_path)
    assert loaded["workspace"]["mode"] == "inherit"
    disk = record_from_disk(staged.record.artifacts_dir)
    assert disk.agent_meta is not None
    assert disk.agent_meta.agent_session_turn is not None
    assert disk.agent_meta.agent_session_turn.state == "staged"
    handoff = read_staged_handoff(dirs[0])
    assert handoff is not None
    assert handoff["kind"] == "monitor"
    assert handoff["staged_id"] == staged.staged_id
    assert handoff["successor_workspace"] == "inherit"
    assert handoff["carry_allowed"] is True


def test_stage_blocks_lane_and_replays_identical_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    first = stage_monitor(_request(tmp_path, command="sleep 30"))
    dirs.append(first.record.artifacts_dir)

    with pytest.raises(MonitorAlreadyRunningError):
        stage_monitor(_request(tmp_path, command="true"))
    with pytest.raises(MonitorAlreadyRunningError):
        start_monitor(_request(tmp_path, command="true"))

    replayed = stage_monitor(_request(tmp_path, command="sleep 30"))
    assert replayed.replayed is True
    assert replayed.record.monitor_id == first.record.monitor_id
    assert replayed.staged_id == first.staged_id


def test_nested_cwd_and_explicit_lane_freeze_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    primary = tmp_path / "primary"
    primary.mkdir()
    workspace_dir = register_workspace_checkout(primary, 10)
    nested = Path(workspace_dir) / "sase" / "repos" / "external" / "gh" / "sase-core"
    nested.mkdir(parents=True)
    dirs = _stage_env(
        tmp_path,
        monkeypatch,
        cwd=str(nested),
        workspace_num=10,
        workspace_dir=str(primary),
        starter_workspace_dir=workspace_dir,
    )
    staged = stage_monitor(_request(tmp_path, cwd=str(nested)))
    dirs.append(staged.record.artifacts_dir)
    payload = load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    claim = payload["workspace"]["claim_context"]
    assert payload["cwd"] == str(nested)
    assert payload["lane"] == "acme"
    assert int(claim["workspace_num"]) == 10


def test_tool_run_id_is_stable_from_stage_to_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = _stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    staged = stage_monitor(
        _request(tmp_path, command="true", cwd=str(root), profile="verify")
    )
    dirs.append(staged.record.artifacts_dir)
    run_id = staged.record.tool_run_id
    assert run_id
    payload = load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    assert payload["resources"]["tool_run_id"] == run_id
    record = launch_from_persisted_payload(staged.record.artifacts_dir)
    try:
        assert record.tool_run_id == run_id
        assert record.monitor_state == "running"
        assert record.monitor_id == staged.record.monitor_id
    finally:
        wait_for_done(record.artifacts_dir, timeout=30.0)


def test_launcher_exit_keeps_pending_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.tool.liveness import reconcile_unsettled_tool_runs

    root = _sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = _stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    staged = stage_monitor(
        _request(tmp_path, command="true", cwd=str(root), profile="verify")
    )
    dirs.append(staged.record.artifacts_dir)
    run_id = staged.record.tool_run_id
    assert run_id
    shown = tool_run_show(run_id)["run"]
    fact = observe_owner_fact(shown)
    assert fact is not None
    assert fact["state"] == "pending"
    reconcile_unsettled_tool_runs()
    after = tool_run_show(run_id)["run"]
    assert after["state"] == "created"
    assert after.get("terminal_cause") != "launch_failed"
    cleanup_staged_monitor(staged.record.artifacts_dir)


def test_ack_failure_rolls_back_staged_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)

    def _fail_submit(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise ProcSubmitError("ack failed")

    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _fail_submit)
    with pytest.raises(MonitorError, match="ack failed"):
        launch_from_persisted_payload(staged.record.artifacts_dir)
    meta = json.loads(
        (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert meta["monitor_state"] == "failed"
    assert (Path(staged.record.artifacts_dir) / "done.json").is_file()


def test_cleanup_at_resource_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    bare = stage_monitor(_request(tmp_path, command="true"))
    dirs.append(bare.record.artifacts_dir)
    starter = dirs[0]
    result = cleanup_staged_monitor(bare.record.artifacts_dir)
    assert result.held is False
    assert result.member_state == "failed"
    assert result.settled_tool_run_id is None
    assert not (Path(starter) / STAGED_HANDOFF_FILENAME).exists()
    again = cleanup_staged_monitor(bare.record.artifacts_dir)
    assert again.member_state in {"failed", "staged"}


def test_cleanup_releases_staged_join_without_stopping_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    run_id = reserve_detached_run("--", "true", agent="acme")
    staged = stage_monitor(_request(tmp_path, join_run_id=run_id))
    dirs.append(staged.record.artifacts_dir)
    assert staged.record.tool_run_id == run_id
    result = cleanup_staged_monitor(staged.record.artifacts_dir)
    assert result.released_join is True
    assert result.settled_tool_run_id is None
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] == "created"


def test_held_cleanup_keeps_outer_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = _stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    staged = stage_monitor(
        _request(tmp_path, command="true", cwd=str(root), profile="verify")
    )
    dirs.append(staged.record.artifacts_dir)
    run_id = staged.record.tool_run_id
    result = cleanup_staged_monitor(staged.record.artifacts_dir, held=True)
    assert result.held is True
    assert result.settled_tool_run_id == run_id
    assert (Path(dirs[0]) / STAGED_HANDOFF_FILENAME).is_file()
    meta = json.loads(
        (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert meta["monitor_state"] == "staged"
    assert meta.get("monitor_stage_held") is True
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] != "created"
    with pytest.raises(MonitorError, match="canceled run"):
        launch_from_persisted_payload(staged.record.artifacts_dir)


def test_launch_from_persisted_payload_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)
    record = launch_from_persisted_payload(staged.record.artifacts_dir)
    try:
        assert record.monitor_state == "running"
        assert record.pid is not None
        done = wait_for_done(record.artifacts_dir, timeout=30.0)
        assert done["monitor_state"] == "completed"
    except Exception:
        wait_for_done(record.artifacts_dir, timeout=10.0)
        raise


def test_immediate_start_still_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stage_env(tmp_path, monkeypatch)
    record = start_monitor(_request(tmp_path))
    try:
        assert record.monitor_state == "running"
        done = wait_for_done(record.artifacts_dir, timeout=30.0)
        assert done["monitor_state"] == "completed"
    except Exception:
        wait_for_done(record.artifacts_dir, timeout=10.0)
        raise
