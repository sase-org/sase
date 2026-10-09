"""Runner shutdown and exec-loop sweep tests.

Split from ``tests.test_agent_scope_sweep``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def _patch_main_harness(
    monkeypatch: pytest.MonkeyPatch, state: SimpleNamespace, order: list[str]
) -> None:
    import sase.axe.run_agent_runner as runner

    monkeypatch.setattr(runner, "_build_run_state", lambda argv: state)
    monkeypatch.setattr(runner, "_record_completion", lambda s: None)
    monkeypatch.setattr(
        "sase.feature_flags.install_process_feature_flags", lambda: None
    )
    monkeypatch.setattr(
        "sase.agent.scope_sweep.sweep_own_agent_scope",
        lambda context: order.append(f"sweep:{context}"),
    )
    monkeypatch.setattr(
        runner, "finalize_runner_shutdown", lambda **kwargs: order.append("finalize")
    )
    monkeypatch.setattr(
        runner, "cleanup_launch_scratch", lambda **kwargs: order.append("cleanup")
    )
    monkeypatch.setattr(runner, "find_gate_intent_lost_error", lambda e: None)
    monkeypatch.setattr(runner, "record_runner_error", lambda *a, **k: ("s", "t"))


def _harness_state(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        success=True,
        exec_outcome="completed",
        error_summary=None,
        error_traceback_str=None,
        current_artifacts_dir=None,
        artifacts_dir=str(tmp_path),
        suppress_completion_notification=False,
        shutdown_context=lambda: SimpleNamespace(),
        shutdown_state=lambda: SimpleNamespace(),
        error_context=lambda: {},
    )


def _exec_context(tmp_path: Path):
    from sase.axe.run_agent_exec_types import AgentExecContext

    return AgentExecContext(
        cl_name="test",
        project_file="sase",
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "out.md"),
        workspace_num=1,
        timestamp="20260101_000000",
        update_target="",
        project_name="sase",
        is_home_mode=False,
        artifacts_dir=str(tmp_path),
        artifacts_timestamp="20260101_000000",
        vcs_tag=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={},
        local_macros={},
    )


def test_main_sweeps_before_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.axe.run_agent_runner as runner

    order: list[str] = []
    state = SimpleNamespace(
        success=True,
        exec_outcome="completed",
        error_summary=None,
        error_traceback_str=None,
        current_artifacts_dir=None,
        artifacts_dir=str(tmp_path),
        suppress_completion_notification=False,
        shutdown_context=lambda: SimpleNamespace(),
        shutdown_state=lambda: SimpleNamespace(),
        error_context=lambda: {},
    )
    monkeypatch.setattr(runner, "_build_run_state", lambda argv: state)
    monkeypatch.setattr(runner, "_run_agent", lambda s: None)
    monkeypatch.setattr(runner, "_record_completion", lambda s: None)
    monkeypatch.setattr(
        "sase.feature_flags.install_process_feature_flags", lambda: None
    )
    monkeypatch.setattr(
        "sase.agent.scope_sweep.sweep_own_agent_scope",
        lambda context: order.append(f"sweep:{context}"),
    )
    monkeypatch.setattr(
        runner, "finalize_runner_shutdown", lambda **kwargs: order.append("finalize")
    )
    monkeypatch.setattr(
        runner, "cleanup_launch_scratch", lambda **kwargs: order.append("cleanup")
    )
    with pytest.raises(SystemExit) as excinfo:
        runner.main()
    assert excinfo.value.code == 0
    assert order == ["sweep:exit", "finalize", "cleanup"]


def test_main_sweep_failure_still_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.axe.run_agent_runner as runner

    order: list[str] = []
    state = SimpleNamespace(
        success=True,
        exec_outcome="completed",
        error_summary=None,
        error_traceback_str=None,
        current_artifacts_dir=None,
        artifacts_dir="/tmp/x",
        suppress_completion_notification=False,
        shutdown_context=lambda: SimpleNamespace(),
        shutdown_state=lambda: SimpleNamespace(),
        error_context=lambda: {},
    )
    monkeypatch.setattr(runner, "_build_run_state", lambda argv: state)
    monkeypatch.setattr(runner, "_run_agent", lambda s: None)
    monkeypatch.setattr(runner, "_record_completion", lambda s: None)
    monkeypatch.setattr(
        "sase.feature_flags.install_process_feature_flags", lambda: None
    )

    def boom(*, context: str) -> None:
        order.append("sweep")
        raise RuntimeError("sweep failed")

    monkeypatch.setattr("sase.agent.scope_sweep.sweep_own_agent_scope", boom)
    monkeypatch.setattr(
        runner, "finalize_runner_shutdown", lambda **kwargs: order.append("finalize")
    )
    monkeypatch.setattr(
        runner, "cleanup_launch_scratch", lambda **kwargs: order.append("cleanup")
    )
    with pytest.raises(SystemExit):
        runner.main()
    assert order == ["sweep", "finalize", "cleanup"]


def test_main_sweeps_on_agent_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.axe.run_agent_runner as runner

    order: list[str] = []
    _patch_main_harness(monkeypatch, _harness_state(tmp_path), order)
    monkeypatch.setattr(
        runner, "_run_agent", lambda s: (_ for _ in ()).throw(RuntimeError("bad"))
    )
    with pytest.raises(SystemExit) as excinfo:
        runner.main()
    assert excinfo.value.code == 1
    assert order == ["sweep:exit", "finalize", "cleanup"]


def test_main_sweeps_on_plain_system_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.axe.run_agent_runner as runner

    order: list[str] = []
    _patch_main_harness(monkeypatch, _harness_state(tmp_path), order)
    monkeypatch.setattr(runner, "is_user_kill_exit", lambda e: False)
    monkeypatch.setattr(runner, "system_exit_code", lambda e: 3)

    def _exit(s: SimpleNamespace) -> None:
        raise SystemExit(3)

    monkeypatch.setattr(runner, "_run_agent", _exit)
    with pytest.raises(SystemExit):
        runner.main()
    assert order == ["sweep:exit", "finalize", "cleanup"]


def test_main_sweeps_on_user_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.axe.run_agent_runner as runner

    order: list[str] = []
    state = _harness_state(tmp_path)
    _patch_main_harness(monkeypatch, state, order)
    monkeypatch.setattr(runner, "is_user_kill_exit", lambda e: True)
    monkeypatch.setattr(runner, "record_kill_provenance", lambda *a, **k: None)
    monkeypatch.setattr(runner, "killed_at", lambda: 0.0)

    def _exit(s: SimpleNamespace) -> None:
        raise SystemExit(130)

    monkeypatch.setattr(runner, "_run_agent", _exit)
    with pytest.raises(SystemExit):
        runner.main()
    assert state.exec_outcome == "killed"
    assert order == ["sweep:exit", "finalize", "cleanup"]


def test_exec_loop_sweeps_only_from_second_iteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.axe.run_agent_exec as exec_module

    sweeps: list[str] = []
    monkeypatch.setattr(
        "sase.agent.scope_sweep.sweep_own_agent_scope",
        lambda context: sweeps.append(context),
    )
    monkeypatch.setattr(exec_module, "_publish_predicted_chat_path", lambda ctx: None)
    monkeypatch.setattr(exec_module, "_publish_root_timestamp", lambda ctx: None)
    monkeypatch.setattr(exec_module, "_export_exec_agent_tab", lambda ctx, env: None)
    monkeypatch.setattr(exec_module, "_publish_phase_env", lambda *a, **k: None)
    monkeypatch.setattr(exec_module, "_build_named_args", lambda ctx: {})
    monkeypatch.setattr(exec_module, "_resolve_workflow_project", lambda ctx: None)
    monkeypatch.setattr(exec_module, "_handle_killed_iteration", lambda ctx, st: None)
    monkeypatch.setattr(
        exec_module, "_finalize_loop", lambda ctx, state, tracker, result: "done"
    )
    monkeypatch.setattr(exec_module, "reset_killed", lambda: None)
    # First iteration sees a live kill (successor turn follows), the second
    # completes the loop.
    calls = {"n": 0}

    def fake_was_killed() -> bool:
        calls["n"] += 1
        return calls["n"] == 1

    monkeypatch.setattr(exec_module, "was_killed", fake_was_killed)
    monkeypatch.setattr(
        "sase.macro.models.create_anonymous_workflow",
        lambda prompt: SimpleNamespace(name="w", macros=None),
    )
    monkeypatch.setattr(
        "sase.macro.workflow_runner.execute_workflow",
        lambda *a, **k: SimpleNamespace(continuation_prepared_ref=None),
    )
    monkeypatch.setattr(
        "sase.continuation_capture.persist_workspace_facts_best_effort",
        lambda ctx, state: None,
    )
    monkeypatch.setattr(
        "sase.llm_provider.gate_intent_guard.raise_if_gate_intent_lost",
        lambda *a, **k: None,
    )

    result = exec_module._run_execution_loop_bound(_exec_context(tmp_path), "do work")
    assert result == "done"
    assert sweeps == ["turn"]


def test_exec_loop_no_sweep_for_single_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.axe.run_agent_exec as exec_module

    sweeps: list[str] = []
    monkeypatch.setattr(
        "sase.agent.scope_sweep.sweep_own_agent_scope",
        lambda context: sweeps.append(context),
    )
    monkeypatch.setattr(exec_module, "_publish_predicted_chat_path", lambda ctx: None)
    monkeypatch.setattr(exec_module, "_publish_root_timestamp", lambda ctx: None)
    monkeypatch.setattr(exec_module, "_export_exec_agent_tab", lambda ctx, env: None)
    monkeypatch.setattr(exec_module, "_publish_phase_env", lambda *a, **k: None)
    monkeypatch.setattr(exec_module, "_build_named_args", lambda ctx: {})
    monkeypatch.setattr(exec_module, "_resolve_workflow_project", lambda ctx: None)
    monkeypatch.setattr(
        exec_module, "_finalize_loop", lambda ctx, state, tracker, result: "done"
    )
    monkeypatch.setattr(exec_module, "reset_killed", lambda: None)
    monkeypatch.setattr(exec_module, "was_killed", lambda: False)
    monkeypatch.setattr(
        "sase.macro.models.create_anonymous_workflow",
        lambda prompt: SimpleNamespace(name="w", macros=None),
    )
    monkeypatch.setattr(
        "sase.macro.workflow_runner.execute_workflow",
        lambda *a, **k: SimpleNamespace(continuation_prepared_ref=None),
    )
    monkeypatch.setattr(
        "sase.continuation_capture.persist_workspace_facts_best_effort",
        lambda ctx, state: None,
    )
    monkeypatch.setattr(
        "sase.llm_provider.gate_intent_guard.raise_if_gate_intent_lost",
        lambda *a, **k: None,
    )

    assert exec_module._run_execution_loop_bound(_exec_context(tmp_path), "x") == "done"
    assert sweeps == []
