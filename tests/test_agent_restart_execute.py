"""Execution ordering for ``sase agent restart``."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.agent.restart import execute_agent_restart
from tests._agent_restart_helpers import (
    dummy_plan,
    failed_kill,
    make_restartable_agent,
    successful_kill,
)


@pytest.fixture(autouse=True)
def _isolate_sase_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))


def _launch_result() -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=492011,
        workspace_num=14,
        workspace_dir="/tmp/ws",
        output_path="/tmp/out",
        artifacts_dir="/tmp/new-02p",
        agent_name="02p",
    )


def test_failed_kill_aborts_before_wipe_and_launch(tmp_path: Path) -> None:
    artifacts = make_restartable_agent(tmp_path)
    plan = dummy_plan(artifacts)
    calls: list[str] = []

    def kill(*_args: object, **_kwargs: object) -> object:
        calls.append("kill")
        return failed_kill()

    def apply(*_args: object, **_kwargs: object) -> None:
        calls.append("apply")

    def launch(*_args: object, **_kwargs: object) -> list[AgentLaunchResult]:
        calls.append("launch")
        return [_launch_result()]

    with (
        patch("sase.agent.running.kill_named_agent", side_effect=kill),
        patch("sase.agent.running.dismiss_named_agent") as dismiss,
        patch(
            "sase.agent.force_reuse_launch.apply_force_reuse_launch", side_effect=apply
        ),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", side_effect=launch),
    ):
        outcome = execute_agent_restart(plan)

    assert outcome.status == "kill_failed"
    assert calls == ["kill"]
    dismiss.assert_not_called()


def test_done_agent_takes_dismiss_path(tmp_path: Path) -> None:
    artifacts = make_restartable_agent(tmp_path, done=True)
    plan = dummy_plan(artifacts, done=True)
    calls: list[str] = []

    def dismiss(*_args: object, **_kwargs: object) -> object:
        calls.append("dismiss")
        return successful_kill(status="dismissed", pid=None, message="Dismissed")

    def apply(*_args: object, **_kwargs: object) -> None:
        calls.append("apply")

    def launch(*_args: object, **_kwargs: object) -> list[AgentLaunchResult]:
        calls.append("launch")
        return [_launch_result()]

    with (
        patch("sase.agent.running.kill_named_agent") as kill,
        patch("sase.agent.running.dismiss_named_agent", side_effect=dismiss),
        patch(
            "sase.agent.force_reuse_launch.apply_force_reuse_launch", side_effect=apply
        ),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", side_effect=launch),
    ):
        outcome = execute_agent_restart(plan)

    assert outcome.status == "ok"
    assert outcome.stop_action == "dismissed"
    assert calls == ["dismiss", "apply", "launch"]
    kill.assert_not_called()


def test_launch_failure_after_stop_is_partial(tmp_path: Path) -> None:
    artifacts = make_restartable_agent(tmp_path)
    plan = dummy_plan(artifacts)
    calls: list[str] = []

    def kill(*_args: object, **_kwargs: object) -> object:
        calls.append("kill")
        return successful_kill()

    def apply(*_args: object, **_kwargs: object) -> None:
        calls.append("apply")

    def launch(*_args: object, **_kwargs: object) -> list[AgentLaunchResult]:
        calls.append("launch")
        raise RuntimeError("spawn failed")

    with (
        patch("sase.agent.running.kill_named_agent", side_effect=kill),
        patch(
            "sase.agent.force_reuse_launch.apply_force_reuse_launch", side_effect=apply
        ),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", side_effect=launch),
    ):
        outcome = execute_agent_restart(plan)

    assert outcome.status == "partial"
    assert calls == ["kill", "apply", "launch"]
    assert outcome.recovery_dir is not None
    rewritten = Path(outcome.recovery_dir) / "rewritten.md"
    assert rewritten.is_file()
    assert rewritten.read_text(encoding="utf-8") == plan.rewritten_prompt
    assert outcome.recovery_command is not None
    assert "sase run" in outcome.recovery_command
    assert str(rewritten) in outcome.recovery_command


def test_successful_run_wipes_and_launches_once(tmp_path: Path) -> None:
    artifacts = make_restartable_agent(tmp_path)
    plan = dummy_plan(artifacts)
    calls: list[str] = []
    apply_args: list[object] = []
    launch_args: list[tuple[object, object]] = []

    def kill(*_args: object, **kwargs: object) -> object:
        calls.append("kill")
        assert kwargs.get("exact_name") is True
        return successful_kill()

    def apply(force_plan: object) -> None:
        calls.append("apply")
        apply_args.append(force_plan)

    def launch(prompt: object, **kwargs: object) -> list[AgentLaunchResult]:
        calls.append("launch")
        launch_args.append((prompt, kwargs.get("segment_extra_env")))
        return [_launch_result()]

    with (
        patch("sase.agent.running.kill_named_agent", side_effect=kill),
        patch("sase.agent.running.dismiss_named_agent") as dismiss,
        patch(
            "sase.agent.force_reuse_launch.apply_force_reuse_launch", side_effect=apply
        ),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", side_effect=launch),
    ):
        outcome = execute_agent_restart(plan)

    assert outcome.status == "ok"
    assert calls == ["kill", "apply", "launch"]
    assert apply_args == [plan.force_reuse_plan]
    assert launch_args == [(plan.rewritten_prompt, plan.force_reuse_plan.segment_envs)]
    assert outcome.launched_pid == 492011
    assert outcome.launched_workspace_num == 14
    dismiss.assert_not_called()


def test_preflight_is_required_before_execute(tmp_path: Path) -> None:
    """Execute never plans; a caller that skipped planning cannot reach wipe."""
    artifacts = make_restartable_agent(tmp_path)
    plan = dummy_plan(artifacts)
    assert plan.force_reuse_plan is not None
    with patch("sase.agent.running.kill_named_agent", return_value=successful_kill()):
        with patch("sase.agent.force_reuse_launch.apply_force_reuse_launch") as apply:
            with patch(
                "sase.agent.launch_cwd.launch_agents_from_cwd",
                return_value=[_launch_result()],
            ):
                execute_agent_restart(plan)
    apply.assert_called_once_with(plan.force_reuse_plan)


def test_launch_uses_home_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = make_restartable_agent(tmp_path)
    plan = dummy_plan(artifacts)
    seen: list[Path] = []
    home = tmp_path / "operator-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))

    def launch(*_args: object, **_kwargs: object) -> list[AgentLaunchResult]:
        seen.append(Path.cwd())
        return [_launch_result()]

    with (
        patch("sase.agent.running.kill_named_agent", return_value=successful_kill()),
        patch("sase.agent.force_reuse_launch.apply_force_reuse_launch"),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", side_effect=launch),
    ):
        execute_agent_restart(plan)
    assert seen == [home]


def test_recovery_survives_real_artifact_wipe(tmp_path: Path) -> None:
    artifacts = make_restartable_agent(tmp_path)
    plan = dummy_plan(artifacts)

    def apply(*_args: object, **_kwargs: object) -> None:
        shutil.rmtree(artifacts)

    def launch(*_args: object, **_kwargs: object) -> list[AgentLaunchResult]:
        raise RuntimeError("spawn failed")

    with (
        patch("sase.agent.running.kill_named_agent", return_value=successful_kill()),
        patch(
            "sase.agent.force_reuse_launch.apply_force_reuse_launch", side_effect=apply
        ),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", side_effect=launch),
    ):
        outcome = execute_agent_restart(plan)

    assert outcome.status == "partial"
    assert not artifacts.exists()
    assert outcome.recovery_dir is not None
    rewritten = Path(outcome.recovery_dir) / "rewritten.md"
    assert rewritten.is_file()
    assert rewritten.read_text(encoding="utf-8") == plan.rewritten_prompt
    assert outcome.recovery_command is not None
    assert str(rewritten) in outcome.recovery_command


def test_recovery_bundle_is_written_before_kill(tmp_path: Path) -> None:
    artifacts = make_restartable_agent(tmp_path)
    plan = dummy_plan(artifacts)
    found_before_kill: list[Path] = []

    def kill(*_args: object, **_kwargs: object) -> object:
        root = tmp_path / "sase-home" / "restarts"
        found_before_kill.extend(root.glob("*/rewritten.md"))
        return successful_kill()

    with (
        patch("sase.agent.running.kill_named_agent", side_effect=kill),
        patch("sase.agent.force_reuse_launch.apply_force_reuse_launch"),
        patch(
            "sase.agent.launch_cwd.launch_agents_from_cwd",
            return_value=[_launch_result()],
        ),
    ):
        execute_agent_restart(plan)

    assert found_before_kill
    assert found_before_kill[0].is_file()
    assert found_before_kill[0].read_text(encoding="utf-8") == plan.rewritten_prompt


def test_wipe_error_is_wipe_failed_not_traceback(tmp_path: Path) -> None:
    artifacts = make_restartable_agent(tmp_path)
    plan = dummy_plan(artifacts)
    ledger: list[tuple[str, str, str]] = []

    def apply(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Failed to wipe agent name '02p': boom")

    with (
        patch("sase.agent.running.kill_named_agent", return_value=successful_kill()),
        patch(
            "sase.agent.force_reuse_launch.apply_force_reuse_launch", side_effect=apply
        ),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd") as launch,
    ):
        outcome = execute_agent_restart(
            plan,
            progress=lambda step, status, detail: ledger.append((step, status, detail)),
        )

    assert outcome.status == "wipe_failed"
    assert "boom" in (outcome.error or "")
    assert any(step == "name" and status == "fail" for step, status, _detail in ledger)
    launch.assert_not_called()
    assert outcome.recovery_dir is not None


def test_launch_name_mismatch_sets_renamed_to(tmp_path: Path) -> None:
    artifacts = make_restartable_agent(tmp_path)
    plan = dummy_plan(artifacts)
    launched = _launch_result()
    launched.agent_name = "062"
    ledger: list[tuple[str, str, str]] = []

    with (
        patch("sase.agent.running.kill_named_agent", return_value=successful_kill()),
        patch("sase.agent.force_reuse_launch.apply_force_reuse_launch"),
        patch(
            "sase.agent.launch_cwd.launch_agents_from_cwd",
            return_value=[launched],
        ),
    ):
        outcome = execute_agent_restart(
            plan,
            progress=lambda step, status, detail: ledger.append((step, status, detail)),
        )

    assert outcome.status == "ok"
    assert outcome.renamed_to == "062"
    assert any(
        step == "name" and status == "warn" and "062" in detail
        for step, status, detail in ledger
    )
