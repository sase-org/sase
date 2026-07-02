"""Regression tests for partial background launch cleanup."""

from __future__ import annotations

import signal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sase.agent.launch_types import AgentLaunchResult


def _launch_result() -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=1234,
        workspace_num=7,
        workspace_dir="/workspace/7",
        output_path="/tmp/out.txt",
        project_file="/tmp/projects/proj/proj.sase",
        project_name="proj",
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
    )


def test_rollback_partial_launch_results_terminates_and_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.partial_launch import rollback_partial_launch_results

    killed: list[tuple[int, signal.Signals]] = []
    released: list[tuple[str, int, str | None, str | None]] = []
    monkeypatch.setattr("sase.agent.partial_launch.os.getpgid", lambda pid: pid + 10)
    monkeypatch.setattr(
        "sase.agent.partial_launch.os.killpg",
        lambda pgid, sig: killed.append((pgid, sig)),
    )
    monkeypatch.setattr(
        "sase.running_field.release_workspace",
        lambda project_file, workspace_num, workflow, cl_name: released.append(
            (project_file, workspace_num, workflow, cl_name)
        ),
    )

    summary = rollback_partial_launch_results([_launch_result()])

    assert killed == [(1244, signal.SIGTERM)]
    assert released == [
        (
            "/tmp/projects/proj/proj.sase",
            7,
            "ace(run)-260101_120000",
            "proj",
        )
    ]
    assert summary.terminated_pids == (1234,)
    assert summary.released_workspaces == (("/tmp/projects/proj/proj.sase", 7),)


def test_launch_query_rolls_back_partial_multi_prompt_launch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.agent.multi_prompt_launcher import _MultiPromptPartialLaunchError
    from sase.main.query_handler import _launch

    result = _launch_result()

    def fail_launch(query: str) -> list[AgentLaunchResult]:
        del query
        raise _MultiPromptPartialLaunchError([result], RuntimeError("boom"))

    rollback = MagicMock(
        return_value=SimpleNamespace(
            terminated_pids=(result.pid,),
            released_workspaces=((result.project_file, result.workspace_num),),
        )
    )
    monkeypatch.setattr(_launch, "launch_agents_from_cwd", fail_launch)
    monkeypatch.setattr(
        "sase.agent.partial_launch.rollback_partial_launch_results", rollback
    )

    with pytest.raises(SystemExit) as exc_info:
        _launch.launch_query("one\n---\ntwo")

    assert exc_info.value.code == 1
    rollback.assert_called_once_with([result])
    stderr = capsys.readouterr().err
    assert "partial multi-prompt launch failed after spawning 1 child agent" in stderr
    assert "Cause: boom" in stderr


def test_launch_query_prints_each_launched_agent_pid(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dataclasses import replace

    from sase.main.query_handler import _launch

    first = _launch_result()
    second = replace(first, pid=5678, workspace_num=8)
    monkeypatch.setattr(
        _launch,
        "launch_agents_from_cwd",
        lambda _query: [first, second],
    )

    with pytest.raises(SystemExit) as exc_info:
        _launch.launch_query("one\n---\ntwo")

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.splitlines() == [
        "Agent started (PID 1234)",
        "Agent started (PID 5678)",
    ]


def test_launch_query_warns_on_unresolved_xprompt_and_still_launches(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main.query_handler import _launch

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "sase.xprompt.unresolved.scan_query_for_unresolved_references",
        lambda _query: ("reviewww",),
    )
    monkeypatch.setattr("sase.xprompt.loader.get_all_prompts", lambda: {})
    monkeypatch.setattr(
        "sase.output.print_status",
        lambda message, status: warnings.append((message, status)),
    )
    monkeypatch.setattr(
        _launch,
        "launch_agents_from_cwd",
        lambda _query: [_launch_result()],
    )

    with pytest.raises(SystemExit) as exc_info:
        _launch.launch_query("do work #reviewww")

    assert exc_info.value.code == 0
    assert warnings
    assert warnings[0][1] == "warning"
    assert "unknown xprompt reference '#reviewww'" in warnings[0][0]
    assert capsys.readouterr().out == "Agent started (PID 1234)\n"
