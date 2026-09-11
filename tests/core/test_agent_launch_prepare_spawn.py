"""Tests for preparing and spawning Rust-backed agent launches."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time

import pytest

from sase.core.agent_launch_facade import (
    prepare_agent_launch,
    spawn_prepared_agent_process,
)
from sase.core.agent_launch_wire import (
    AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
    AgentLaunchPreparedWire,
    AgentLaunchRequestWire,
)


def test_prepare_agent_launch_rust_writes_prompt_and_returns_process_shape(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    request = AgentLaunchRequestWire(
        schema_version=AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        cl_name="feature/test",
        project_file="/tmp/project.sase",
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
    assert Path(prepared.prompt_file).name.startswith("sase_ace_prompt_")
    assert Path(prepared.prompt_file).suffix == ".md"
    assert prepared.output_path == str(
        output_root / "feature_test_ace-run-260501_120000.txt"
    )
    assert prepared.argv == [
        "/venv/bin/python",
        "/repo/run_agent_runner.py",
        "feature/test",
        "/tmp/project.sase",
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
        project_file="/tmp/home.sase",
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
        sase_tmpdir=str(tmp_path),
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
        sase_tmpdir=str(tmp_path),
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


def _wait_for_output_containing(
    path: Path, expected_parts: tuple[str, ...], timeout: float = 5.0
) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text()
            if all(expected in text for expected in expected_parts):
                return text
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
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
    output = _wait_for_output_containing(
        Path(prepared.output_path), ("env-ok", "stderr-line")
    )
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
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
    assert not _pid_alive(seen_pid[0])


@pytest.mark.skipif(os.name != "posix", reason="uses POSIX pid liveness check")
def test_spawn_prepared_agent_process_propagates_workspace_claim_error_type(
    tmp_path: Path,
) -> None:
    """The pyo3/FFI boundary must preserve WorkspaceClaimError's type."""
    pytest.importorskip("sase_core_rs")
    from sase.running_field import WorkspaceClaimError

    seen_pid: list[int] = []
    prepared = _prepared_process(
        tmp_path,
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )

    def fail_claim(pid: int) -> bool:
        seen_pid.append(pid)
        raise WorkspaceClaimError(
            "Failed to claim workspace #100: simulated race", workspace_num=100
        )

    with pytest.raises(WorkspaceClaimError, match="simulated race") as excinfo:
        spawn_prepared_agent_process(
            prepared,
            env=dict(os.environ),
            claim_callback=fail_claim,
        )

    assert excinfo.value.workspace_num == 100
    assert seen_pid
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and _pid_alive(seen_pid[0]):
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
    assert not _pid_alive(seen_pid[0])
