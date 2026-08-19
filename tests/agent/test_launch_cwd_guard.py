"""Launcher and ``sase run`` integration for the fail-closed launch guard."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launch_guard import DisabledProviderLaunchError, LaunchUnitInput
from sase.agent.launch_types import AgentLaunchResult
from sase.ops.models import DurableOperationRequest
from sase.ops.names import RUN_LAUNCH
from tests.agent._launch_guard_helpers import (
    disable,
    install_disables,
    pin_cli_available,
)
from tests._workspace_provider_helpers import patch_no_workspace_metadata


def _launch_result(pid: int = 1234) -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=pid,
        workspace_num=7,
        workspace_dir="/workspace/7",
        output_path="/tmp/out.txt",
        project_file="/tmp/projects/proj/proj.sase",
        project_name="proj",
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
    )


def _spawn_mock() -> MagicMock:
    spawn = MagicMock(return_value=_launch_result())
    return spawn


def _isolated_cwd_launch(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    patch_no_workspace_metadata(monkeypatch)
    spawn = _spawn_mock()
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda create_missing=False: (None, None, None),
    )
    monkeypatch.setattr(
        "sase.history.prompt.add_or_update_prompt", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
        lambda count, **kwargs: [f"ts-{i}" for i in range(count)],
    )
    monkeypatch.setattr("sase.agent.names.get_reserved_agent_names", lambda: set())
    monkeypatch.setattr("sase.agent.launcher.spawn_agent_subprocess", spawn)
    monkeypatch.setattr(
        "sase.running_field.get_first_available_axe_workspace",
        MagicMock(side_effect=AssertionError("workspace must not be claimed")),
    )
    monkeypatch.setattr(
        "sase.running_field.get_workspace_directory_for_num",
        MagicMock(side_effect=AssertionError("workspace must not be claimed")),
    )
    return spawn


def test_blocked_prompt_raises_before_spawn_and_records_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawn = _isolated_cwd_launch(monkeypatch)
    pin_cli_available(monkeypatch)
    install_disables(monkeypatch, {"claude": disable("claude")})
    recorded: list[str] = []
    monkeypatch.setattr(
        "sase.history.prompt.record_failed_launch_prompt",
        recorded.append,
    )
    from sase.agent.launcher import launch_agents_from_cwd

    with pytest.raises(DisabledProviderLaunchError) as exc_info:
        launch_agents_from_cwd("%model:claude/opus Fix the flaky selector")

    spawn.assert_not_called()
    assert recorded == ["%model:claude/opus Fix the flaky selector"]
    assert "Launch Control" in str(exc_info.value)
    assert "claude/opus" in str(exc_info.value)


def test_internal_guard_failure_logs_and_launches(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    spawn = _isolated_cwd_launch(monkeypatch)
    execution = MagicMock()
    execution.results = [_launch_result()]
    plan = MagicMock(return_value=execution)
    monkeypatch.setattr(
        "sase.agent.launch_executor.execute_launch_plan",
        plan,
    )

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise ValueError("guard exploded")

    monkeypatch.setattr(
        "sase.agent.launch_guard.blocked_launch_units",
        _boom,
    )
    from sase.agent.launcher import launch_agents_from_cwd

    with caplog.at_level(logging.WARNING, logger="sase.agent.launch_cwd_agents"):
        results = launch_agents_from_cwd("do work")

    assert results == execution.results
    plan.assert_called()
    spawn.assert_not_called()
    assert "failed open" in caplog.text


def test_launch_units_bundle_launches_exactly_those_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolated_cwd_launch(monkeypatch)
    captured: dict[str, Any] = {}

    def _capture_multi(**kwargs: Any) -> list[AgentLaunchResult]:
        captured.update(kwargs)
        return [_launch_result(1), _launch_result(2)]

    monkeypatch.setattr(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        _capture_multi,
    )
    from sase.agent.launcher import launch_agents_from_cwd

    raw_prompt = "one\n---\ntwo\n---\nthree"
    results = launch_agents_from_cwd(
        raw_prompt,
        launch_units=(
            LaunchUnitInput(
                prompt="kept first",
                template_group="xprompt:team:0",
                swarm_xprompts=("team",),
            ),
            LaunchUnitInput(prompt="kept second"),
        ),
    )

    assert len(results) == 2
    assert captured["segments"] == ["kept first", "kept second"]
    assert captured["segment_template_groups"] == ["xprompt:team:0", None]
    assert captured["segment_swarm_xprompts"] == [("team",), ()]


def test_shorter_bundle_launches_fewer_agents_than_the_raw_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolated_cwd_launch(monkeypatch)
    captured: list[list[str]] = []

    def _capture_multi(**kwargs: Any) -> list[AgentLaunchResult]:
        captured.append(list(kwargs["segments"]))
        return [_launch_result(index) for index, _ in enumerate(kwargs["segments"])]

    monkeypatch.setattr(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        _capture_multi,
    )
    from sase.agent.launcher import launch_agents_from_cwd

    raw = "one\n---\ntwo\n---\nthree"
    full = launch_agents_from_cwd(raw)
    shorter = launch_agents_from_cwd(
        raw,
        launch_units=(LaunchUnitInput(prompt="one"), LaunchUnitInput(prompt="three")),
    )

    assert len(full) == 3
    assert len(shorter) == 2
    assert captured[0] == ["one", "two", "three"]
    assert captured[1] == ["one", "three"]


def _run_launch_query(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
    *,
    expect_launch: bool = True,
) -> tuple[Any, Any, SystemExit]:
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    request = DurableOperationRequest(operation=RUN_LAUNCH, payload=payload)
    launch_kwargs: dict[str, Any] = {}
    if expect_launch:
        launch_kwargs["return_value"] = [_launch_result()]
    emit = MagicMock()
    with (
        patch("sase.ops.cli.load_request", return_value=request),
        patch("sase.agent.prompt_inputs.missing_required_input_names", return_value=[]),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=[],
        ),
        patch(
            "sase.main.query_handler._launch.launch_agents_from_cwd",
            **launch_kwargs,
        ) as mock_launch,
        patch("sase.ops.commands.run.emit_run_launch_result", emit),
        pytest.raises(SystemExit) as exc_info,
    ):
        launch_query(str(payload.get("prompt", "do work")))
    return mock_launch, emit, exc_info.value


def test_launch_query_threads_a_well_formed_launch_units_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_launch, _emit, exit_exc = _run_launch_query(
        monkeypatch,
        {
            "prompt": "one\n---\ntwo",
            "launch_units": [
                {
                    "prompt": "one",
                    "template_group": "xprompt:team:0",
                    "swarm_xprompts": ["team"],
                }
            ],
        },
    )

    assert exit_exc.code == 0
    args, kwargs = mock_launch.call_args
    assert args[0] == "one\n---\ntwo"
    units = kwargs["launch_units"]
    assert len(units) == 1
    assert units[0].prompt == "one"
    assert units[0].template_group == "xprompt:team:0"
    assert units[0].swarm_xprompts == ("team",)


def test_launch_query_rejects_malformed_launch_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_launch, emit, exit_exc = _run_launch_query(
        monkeypatch,
        {
            "prompt": "do work",
            "launch_units": [{"prompt": "x"}],
        },
        expect_launch=False,
    )

    assert exit_exc.code == 1
    mock_launch.assert_not_called()
    emit.assert_called()
    assert emit.call_args.kwargs["success"] is False
    assert "launch_units" in emit.call_args.kwargs["message"]


def test_launch_query_prefers_force_reuse_over_a_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.launch_validation.wipe_names_for_forced_reuse",
        lambda names: None,
    )
    mock_launch, emit, exit_exc = _run_launch_query(
        monkeypatch,
        {
            "prompt": "%id:!foo\nDo work",
            "allow_force_reuse": True,
            "launch_units": [
                {
                    "prompt": "must not launch",
                    "template_group": None,
                    "swarm_xprompts": [],
                }
            ],
        },
    )

    assert exit_exc.code == 0
    emit.assert_called()
    args, kwargs = mock_launch.call_args
    assert args[0] == "%id:foo\nDo work"
    assert kwargs.get("launch_units") is None
    assert kwargs.get("segment_extra_env") is not None
