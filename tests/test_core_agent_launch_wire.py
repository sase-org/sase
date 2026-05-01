"""Tests for the Rust-backed agent-launch wire contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import pytest

from sase.core.agent_launch_facade import (
    LaunchTimestampBatchAllocator,
    allocate_launch_timestamp_batch,
    fake_output_path,
    fake_prompt_path,
    plan_agent_launch_fanout,
    plan_fake_fanout,
    prepare_agent_launch,
    safe_launch_name,
    spawn_prepared_agent_process,
)
from sase.core.agent_launch_wire import (
    AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
    AgentLaunchPreparedWire,
    AgentLaunchRequestWire,
    WorkspaceClaimRequestWire,
    agent_launch_wire_to_json_dict,
    launch_fanout_plan_from_dict,
    workspace_claim_request_from_dict,
)


def test_agent_launch_schema_version_pinned() -> None:
    assert AGENT_LAUNCH_WIRE_SCHEMA_VERSION == 1


def test_workspace_claim_request_round_trips_json_shape() -> None:
    request = WorkspaceClaimRequestWire(
        project_file="/tmp/project.gp",
        workspace_num=2,
        workflow_name="ace(run)-260501_120000",
        pid=123,
        cl_name="feature",
        artifacts_timestamp="20260501120000",
        transfer_from_pid=99,
    )

    payload = agent_launch_wire_to_json_dict(request)
    assert json.loads(json.dumps(payload)) == {
        "project_file": "/tmp/project.gp",
        "workspace_num": 2,
        "workflow_name": "ace(run)-260501_120000",
        "pid": 123,
        "cl_name": "feature",
        "artifacts_timestamp": "20260501120000",
        "transfer_from_pid": 99,
        "pinned": False,
    }
    assert workspace_claim_request_from_dict(payload) == request


def test_prepare_agent_launch_rust_writes_prompt_and_returns_process_shape(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    request = AgentLaunchRequestWire(
        schema_version=AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        cl_name="feature/test",
        project_file="/tmp/project.gp",
        workspace_dir="/tmp/ws",
        workspace_num=4,
        workflow_name="ace(run)-260501_120000",
        prompt="fix it",
        timestamp="260501_120000",
        update_target="p4head",
        project_name="proj",
        history_sort_key="feature/test",
        vcs_workflow_type="gh",
        vcs_ref="feature/test",
        local_xprompts_file="/tmp/xprompts.json",
        extra_env={"SASE_AGENT": "caller", "SASE_REPEAT_NAME": "task.1"},
        retry_transfer_from_pid=99,
    )
    prompt_root = tmp_path / "tmp"
    output_root = tmp_path / "workflows" / "202605"
    prompt_root.mkdir()

    prepared = prepare_agent_launch(
        request,
        python_executable="/venv/bin/python",
        runner_script="/repo/run_agent_runner.py",
        sase_tmpdir=str(prompt_root),
        output_root=str(output_root),
        preallocated_env={
            "GH_PRE_ALLOCATED": "1",
            "GH_WORKSPACE_NUM": "4",
            "GH_WORKSPACE_DIR": "/tmp/ws",
        },
    )

    assert Path(prepared.prompt_file).read_text() == "fix it"
    assert Path(prepared.prompt_file).parent == prompt_root
    assert prepared.output_path == str(
        output_root / "feature_test_ace-run-260501_120000.txt"
    )
    assert prepared.argv == [
        "/venv/bin/python",
        "/repo/run_agent_runner.py",
        "feature/test",
        "/tmp/project.gp",
        "/tmp/ws",
        prepared.output_path,
        "4",
        "ace(run)-260501_120000",
        prepared.prompt_file,
        "260501_120000",
        "p4head",
        "proj",
        "feature/test",
        "",
    ]
    assert prepared.env_delta["SASE_AGENT"] == "1"
    assert prepared.env_delta["SASE_REPEAT_NAME"] == "task.1"
    assert prepared.env_delta["GH_PRE_ALLOCATED"] == "1"
    assert prepared.env_delta["SASE_AGENT_LOCAL_XPROMPTS"] == "/tmp/xprompts.json"
    assert "SASE_AGENT_VCS_WORKFLOW_TYPE" not in prepared.env_delta
    assert prepared.claim_request is not None
    assert prepared.claim_request.workspace_num == 4
    assert prepared.claim_request.transfer_from_pid == 99


def test_prepare_agent_launch_rust_deferred_vcs_env_and_home_claim(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    base = AgentLaunchRequestWire(
        schema_version=AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        cl_name="home",
        project_file="/tmp/home.gp",
        workspace_dir="/home/me",
        workspace_num=9,
        workflow_name="ace(run)-260501_120000",
        prompt="fix it",
        timestamp="260501_120000",
        vcs_workflow_type="gh",
        vcs_ref="feature/test",
        deferred_workspace=True,
    )

    deferred = prepare_agent_launch(
        base,
        python_executable="python",
        runner_script="runner.py",
        sase_tmpdir=None,
        output_root=str(tmp_path),
    )
    assert deferred.claim_request is not None
    assert deferred.claim_request.workspace_num == 0
    assert deferred.env_delta["SASE_AGENT_DEFERRED_WORKSPACE"] == "1"
    assert deferred.env_delta["SASE_AGENT_VCS_WORKFLOW_TYPE"] == "gh"

    home = prepare_agent_launch(
        AgentLaunchRequestWire(**{**base.__dict__, "is_home_mode": True}),
        python_executable="python",
        runner_script="runner.py",
        sase_tmpdir=None,
        output_root=str(tmp_path),
    )
    assert home.claim_request is None
    assert home.argv[-1] == "1"


def _prepared_process(
    tmp_path: Path,
    argv: list[str],
    *,
    cwd: Path | None = None,
) -> AgentLaunchPreparedWire:
    return AgentLaunchPreparedWire(
        schema_version=AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        prompt_file=str(tmp_path / "prompt.md"),
        output_path=str(tmp_path / "agent.log"),
        safe_name="agent",
        argv=argv,
        cwd=str(cwd or tmp_path),
        env_delta={},
        claim_request=None,
    )


def _wait_for_output(path: Path, expected: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text()
            if expected in text:
                return text
        time.sleep(0.02)
    return path.read_text() if path.exists() else ""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_spawn_prepared_agent_process_redirects_output_and_env(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    prepared = _prepared_process(
        tmp_path,
        [
            sys.executable,
            "-c",
            (
                "import os, sys; "
                "print(os.environ['SASE_TEST_ENV']); "
                "print('stderr-line', file=sys.stderr)"
            ),
        ],
    )

    pid = spawn_prepared_agent_process(
        prepared,
        env={**os.environ, "SASE_TEST_ENV": "env-ok"},
        claim_callback=lambda child_pid: child_pid > 0,
    )

    assert pid > 0
    output = _wait_for_output(Path(prepared.output_path), "stderr-line")
    assert "env-ok" in output
    assert "stderr-line" in output


def test_spawn_prepared_agent_process_reports_bad_cwd(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    prepared = _prepared_process(
        tmp_path,
        [sys.executable, "-c", "print('unreachable')"],
        cwd=tmp_path / "missing",
    )

    with pytest.raises(RuntimeError, match="failed to spawn prepared agent process"):
        spawn_prepared_agent_process(prepared, env=dict(os.environ))


@pytest.mark.skipif(os.name != "posix", reason="uses POSIX pid liveness check")
def test_spawn_prepared_agent_process_cleans_up_on_claim_failure(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    seen_pid: list[int] = []
    prepared = _prepared_process(
        tmp_path,
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )

    def fail_claim(pid: int) -> bool:
        seen_pid.append(pid)
        raise RuntimeError("claim failed deliberately")

    with pytest.raises(RuntimeError, match="claim failed deliberately"):
        spawn_prepared_agent_process(
            prepared,
            env=dict(os.environ),
            claim_callback=fail_claim,
        )

    assert seen_pid
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and _pid_alive(seen_pid[0]):
        time.sleep(0.02)
    assert not _pid_alive(seen_pid[0])


def test_fanout_plan_round_trips_slots() -> None:
    plan = plan_fake_fanout(
        "multi_prompt",
        ["first", "%wait\nsecond"],
        fanout_sleep_seconds=0.0,
        requires_sequential_naming_wait=True,
    )
    payload = agent_launch_wire_to_json_dict(plan)

    assert payload["schema_version"] == AGENT_LAUNCH_WIRE_SCHEMA_VERSION
    assert payload["slots"][1]["prompt"] == "%wait\nsecond"
    assert launch_fanout_plan_from_dict(payload) == plan


def test_plan_agent_launch_fanout_rust_multi_prompt() -> None:
    pytest.importorskip("sase_core_rs")

    plan = plan_agent_launch_fanout(
        "one\n```\n---\n```\n---\n%wait\ntwo",
        launch_kind="multi_prompt",
    )

    assert plan.launch_kind == "multi_prompt"
    assert [slot.prompt for slot in plan.slots] == ["one\n```\n---\n```", "%wait\ntwo"]
    assert plan.slots[1].wait_for_previous is True
    assert plan.requires_sequential_naming_wait is True


def test_plan_agent_launch_fanout_rust_model_and_alt() -> None:
    pytest.importorskip("sase_core_rs")

    plan = plan_agent_launch_fanout(
        "%n:foo\n%model:opus\n%model:sonnet %alt(x,y)\nReview",
        launch_kind="model",
    )

    assert plan.launch_kind == "model"
    assert len(plan.slots) == 4
    assert plan.slots[0].model == "opus"
    assert plan.slots[0].prompt == "%n:foo\n%model:opus\n x\nReview"
    assert plan.slots[3].model == "sonnet"
    assert plan.slots[3].prompt == "%n:foo\n%model:sonnet\n y\nReview"


def test_plan_agent_launch_fanout_rust_repeat() -> None:
    pytest.importorskip("sase_core_rs")

    plan = plan_agent_launch_fanout(
        "%r:3 %n:task %model:opus do work",
        launch_kind="repeat",
    )

    assert plan.launch_kind == "repeat"
    assert len(plan.slots) == 3
    assert plan.slots[0].repeat_name == "task"
    assert plan.slots[0].prompt == "  %model:opus do work"
    assert [slot.wait_for_previous for slot in plan.slots] == [False, True, True]


def test_allocate_launch_timestamp_batch_uses_rust_unique_seconds() -> None:
    pytest.importorskip("sase_core_rs")

    assert allocate_launch_timestamp_batch(
        3,
        base_timestamp="260501_120000",
    ) == ["260501_120000", "260501_120001", "260501_120002"]


def test_launch_timestamp_allocator_tracks_previous_batch() -> None:
    pytest.importorskip("sase_core_rs")
    allocator = LaunchTimestampBatchAllocator()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "sase.core.time.generate_timestamp",
            lambda: "260501_120000",
        )
        assert allocator.allocate(2) == ["260501_120000", "260501_120001"]
        assert allocator.allocate(2) == ["260501_120002", "260501_120003"]


def test_fake_paths_match_launch_safe_name_contract(tmp_path: Path) -> None:
    assert safe_launch_name("feature/test:1") == "feature_test_1"
    assert fake_prompt_path(tmp_path, "260501_120000").endswith(
        "sase_ace_prompt_260501_120000.md"
    )
    assert fake_output_path(tmp_path, "feature/test", "260501_120000").endswith(
        "feature_test_ace-run-260501_120000.txt"
    )
