"""Tests for the Phase 1 agent-launch wire contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.agent_launch_facade import (
    LaunchTimestampBatchAllocator,
    allocate_launch_timestamp_batch,
    fake_output_path,
    fake_prompt_path,
    plan_fake_fanout,
    prepare_agent_launch,
    prepare_agent_launch_python,
    safe_launch_name,
)
from sase.core.agent_launch_wire import (
    AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
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


def test_prepare_agent_launch_python_pins_argv_env_and_claim() -> None:
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
        extra_env={"SASE_REPEAT_NAME": "task.1"},
    )

    prepared = prepare_agent_launch_python(
        request,
        python_executable="/venv/bin/python",
        runner_script="/repo/run_agent_runner.py",
        prompt_file="/tmp/prompt.md",
        output_path="/tmp/out.txt",
    )

    assert prepared.schema_version == AGENT_LAUNCH_WIRE_SCHEMA_VERSION
    assert prepared.safe_name == "feature_test"
    assert prepared.argv == [
        "/venv/bin/python",
        "/repo/run_agent_runner.py",
        "feature/test",
        "/tmp/project.gp",
        "/tmp/ws",
        "/tmp/out.txt",
        "4",
        "ace(run)-260501_120000",
        "/tmp/prompt.md",
        "260501_120000",
        "p4head",
        "proj",
        "feature/test",
        "",
    ]
    assert prepared.env_delta["SASE_AGENT"] == "1"
    assert "SASE_AGENT_VCS_WORKFLOW_TYPE" not in prepared.env_delta
    assert prepared.env_delta["SASE_REPEAT_NAME"] == "task.1"
    assert prepared.claim_request is not None
    assert prepared.claim_request.workspace_num == 4


def test_deferred_and_home_prepared_claim_shapes() -> None:
    base = AgentLaunchRequestWire(
        schema_version=AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        cl_name="home",
        project_file="/tmp/home.gp",
        workspace_dir="/home/me",
        workspace_num=9,
        workflow_name="ace(run)-260501_120000",
        prompt="fix it",
        timestamp="260501_120000",
        deferred_workspace=True,
    )

    deferred = prepare_agent_launch_python(
        base,
        python_executable="python",
        runner_script="runner.py",
        prompt_file="prompt.md",
        output_path="out.txt",
    )
    assert deferred.claim_request is not None
    assert deferred.claim_request.workspace_num == 0
    assert deferred.env_delta["SASE_AGENT_DEFERRED_WORKSPACE"] == "1"

    home = prepare_agent_launch_python(
        AgentLaunchRequestWire(**{**base.__dict__, "is_home_mode": True}),
        python_executable="python",
        runner_script="runner.py",
        prompt_file="prompt.md",
        output_path="out.txt",
    )
    assert home.claim_request is None


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
