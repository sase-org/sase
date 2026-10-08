"""Unit tests for the agent-scope sweep (runner teardown)."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent._scope_sweep_core import (
    execute_scope_sweep,
    is_agent_runner,
    plan_scope_sweep,
    read_scope_members,
)
from sase.agent._scope_sweep_own import _own_agent_scope
from sase.agent._scope_sweep_types import ScopeMember
from sase.agent.scope_sweep import (
    AGENT_SCOPE_UNIT_PREFIX,
    RUNNER_SCRIPT_NAME,
    sweep_own_agent_scope,
)

_SCOPE_UNIT = f"{AGENT_SCOPE_UNIT_PREFIX}-999-1234567890.scope"
_SCOPE_CGROUP = (
    "0::/user.slice/user-1000.slice/user@1000.service/app.slice/" + _SCOPE_UNIT + "\n"
)


def _write_stat(
    proc_root: Path,
    pid: int,
    *,
    ppid: int = 1,
    state: str = "S",
    start_ticks: int = 1000,
    comm: str | None = None,
) -> None:
    name = comm if comm is not None else f"proc{pid}"
    fields = [
        state,
        str(ppid),
        "1",
        "1",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "1",
        "0",
        str(start_ticks),
    ]
    proc_dir = proc_root / str(pid)
    proc_dir.mkdir(parents=True, exist_ok=True)
    (proc_dir / "stat").write_text(
        f"{pid} ({name}) {' '.join(fields)} 0 0 0\n", encoding="utf-8"
    )
    (proc_dir / "comm").write_text(f"{name}\n", encoding="utf-8")


def _write_proc(
    proc_root: Path,
    pid: int,
    argv: list[str],
    *,
    ppid: int = 1,
    state: str = "S",
    start_ticks: int = 1000,
    comm: str | None = None,
) -> None:
    _write_stat(
        proc_root, pid, ppid=ppid, state=state, start_ticks=start_ticks, comm=comm
    )
    proc_dir = proc_root / str(pid)
    (proc_dir / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (proc_dir / "cgroup").write_text(_SCOPE_CGROUP, encoding="utf-8")


def _make_scope(
    tmp_path: Path, pids: list[int], *, proc_root: Path
) -> tuple[Path, Path]:
    cgroup_root = tmp_path / "cgroup"
    scope_dir = (
        cgroup_root
        / "user.slice"
        / "user-1000.slice"
        / "user@1000.service"
        / "app.slice"
        / _SCOPE_UNIT
    )
    scope_dir.mkdir(parents=True)
    (scope_dir / "cgroup.procs").write_text(
        "".join(f"{pid}\n" for pid in pids), encoding="utf-8"
    )
    self_dir = proc_root / str(os.getpid())
    self_dir.mkdir(parents=True, exist_ok=True)
    (self_dir / "cgroup").write_text(_SCOPE_CGROUP, encoding="utf-8")
    (self_dir / "cmdline").write_bytes(
        b"python\0/opt/sase/src/sase/axe/" + RUNNER_SCRIPT_NAME.encode() + b"\0"
    )
    _write_stat(proc_root, os.getpid(), ppid=1)
    return scope_dir, cgroup_root


def _member(
    pid: int, ppid: int = 1, comm: str = "sh", argv: tuple[str, ...] = ("sh",)
) -> ScopeMember:
    return ScopeMember(pid=pid, ppid=ppid, comm=comm, argv=argv, identity=f"boot:{pid}")


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps = 0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds


def test_protect_root_descendants_survive() -> None:
    runner = _member(100, ppid=1, argv=("python", "run_agent_runner.py"))
    child = _member(101, ppid=100)
    grandchild = _member(102, ppid=101)
    leak = _member(103, ppid=1)
    plan = plan_scope_sweep(
        [runner, child, grandchild, leak], protect_root=runner, spare_patterns=()
    )
    assert {m.pid for m in plan.protected} == {100, 101, 102}
    assert [m.pid for m in plan.targets] == [103]
    assert plan.spared == ()


def test_protect_root_pid_form() -> None:
    runner = _member(100, ppid=1)
    child = _member(101, ppid=100)
    plan = plan_scope_sweep([runner, child], protect_root=100, spare_patterns=())
    assert {m.pid for m in plan.protected} == {100, 101}
    assert plan.targets == ()


def test_spare_by_comm_and_cmdline_plus_descendants() -> None:
    agent = _member(200, ppid=1, argv=("sshd",))
    ssh_agent = _member(
        201, ppid=1, comm="ssh-agent", argv=("ssh-agent", "-a", "/tmp/sock")
    )
    mux = _member(202, ppid=1, comm="ssh", argv=("ssh:", "user@host", "[mux]"))
    mux_child = _member(203, ppid=202, argv=("sh",))
    leak = _member(204, ppid=1)
    plan = plan_scope_sweep(
        [agent, ssh_agent, mux, mux_child, leak],
        protect_root=agent,
        spare_patterns=(
            "^ssh-agent$",
            "^gpg-agent$",
            "^tmux: server$",
            r"^ssh: .*\[mux\]$",
        ),
    )
    assert {m.pid for m in plan.spared} == {201, 202, 203}
    assert [m.pid for m in plan.targets] == [204]


def test_is_agent_runner_first_three_argv() -> None:
    assert is_agent_runner(_member(1, argv=("python", "run_agent_runner.py", "--x")))
    assert is_agent_runner(
        _member(1, argv=("python", "-u", "/a/b/run_agent_runner.py"))
    )
    assert not is_agent_runner(_member(1, argv=("python", "other.py")))
    assert not is_agent_runner(
        _member(
            1,
            argv=("a", "b", "c", "run_agent_runner.py"),
        )
    )


def test_read_scope_members_skips_zombie_and_unreadable(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    scope_dir = tmp_path / "scope"
    scope_dir.mkdir()
    _write_proc(proc_root, 300, ["sleep", "10"])
    _write_proc(proc_root, 301, ["sleep", "10"], state="Z")
    _write_stat(proc_root, 302, ppid=1)  # no comm/cmdline: unreadable
    (scope_dir / "cgroup.procs").write_text("300\n301\n302\n999\n", encoding="utf-8")
    members = read_scope_members(scope_dir, proc_root=proc_root)
    assert [m.pid for m in members] == [300]
    assert members[0].argv == ("sleep", "10")


def test_execute_identity_pinning_skips_recycled_pid(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    scope_dir = tmp_path / "scope"
    scope_dir.mkdir()
    _write_proc(proc_root, 400, ["busy-loop"], start_ticks=100)
    (scope_dir / "cgroup.procs").write_text("400\n", encoding="utf-8")
    members = read_scope_members(scope_dir, proc_root=proc_root)
    assert len(members) == 1
    plan = plan_scope_sweep(members, protect_root=None, spare_patterns=())
    assert [m.pid for m in plan.targets] == [400]
    # The target exits and its pid is recycled by a process outside the
    # scope: the scope no longer lists it, and its start time changed.
    _write_proc(proc_root, 400, ["innocent"], start_ticks=999)
    (scope_dir / "cgroup.procs").write_text("", encoding="utf-8")

    calls: list[tuple[int, int]] = []
    clock = _Clock()
    result = execute_scope_sweep(
        plan,
        scope_dir,
        grace_seconds=0,
        proc_root=proc_root,
        kill=lambda pid, sig: calls.append((pid, int(sig))),
        clock=clock.clock,
        sleep=clock.sleep,
    )
    assert calls == []
    assert result.terminated == ()


def test_execute_grace_escalation_term_then_kill(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    scope_dir = tmp_path / "scope"
    scope_dir.mkdir()
    _write_proc(proc_root, 500, ["busy-loop"])
    (scope_dir / "cgroup.procs").write_text("500\n", encoding="utf-8")
    members = read_scope_members(scope_dir, proc_root=proc_root)
    plan = plan_scope_sweep(members, protect_root=None, spare_patterns=())

    calls: list[tuple[int, int]] = []
    clock = _Clock()
    result = execute_scope_sweep(
        plan,
        scope_dir,
        grace_seconds=1.0,
        proc_root=proc_root,
        kill=lambda pid, sig: calls.append((pid, int(sig))),
        clock=clock.clock,
        sleep=clock.sleep,
    )
    kinds = [sig for _, sig in calls]
    assert kinds[0] == int(signal.SIGTERM)
    assert int(signal.SIGKILL) in kinds
    # The fake member never exits, so it is reported as a survivor.
    assert [m.pid for m in result.survivors] == [500]
    assert result.rounds >= 1


def test_execute_late_arrival_gets_sigkill_directly(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    scope_dir = tmp_path / "scope"
    scope_dir.mkdir()
    _write_proc(proc_root, 600, ["first"])
    (scope_dir / "cgroup.procs").write_text("600\n", encoding="utf-8")
    members = read_scope_members(scope_dir, proc_root=proc_root)
    plan = plan_scope_sweep(members, protect_root=None, spare_patterns=())

    calls: list[tuple[int, int]] = []
    clock = _Clock()

    def fake_kill(pid: int, sig: int) -> None:
        calls.append((pid, int(sig)))
        if pid == 600 and int(sig) == int(signal.SIGTERM):
            # A second leak appears mid-sweep, after the TERM round.
            _write_proc(proc_root, 601, ["late"])
            (scope_dir / "cgroup.procs").write_text("600\n601\n", encoding="utf-8")

    execute_scope_sweep(
        plan,
        scope_dir,
        grace_seconds=0,
        proc_root=proc_root,
        kill=fake_kill,
        clock=clock.clock,
        sleep=clock.sleep,
    )
    late_calls = [sig for pid, sig in calls if pid == 601]
    assert late_calls
    assert all(sig == int(signal.SIGKILL) for sig in late_calls)


def test_invalid_spare_regex_is_ignored() -> None:
    leak = _member(700)
    plan = plan_scope_sweep([leak], protect_root=None, spare_patterns=("[bad",))
    assert [m.pid for m in plan.targets] == [700]


def test__own_agent_scope_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc_root = tmp_path / "proc"
    scope_dir, cgroup_root = _make_scope(tmp_path, [], proc_root=proc_root)
    monkeypatch.delenv("SASE_DETACH_SCOPE_DISABLE", raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    monkeypatch.setattr("sase.agent._scope_sweep_own.sys.platform", "linux")

    assert (
        _own_agent_scope(proc_root=proc_root, cgroup_root=cgroup_root, enabled=True)
        == scope_dir
    )

    # Disabled config declines.
    assert (
        _own_agent_scope(proc_root=proc_root, cgroup_root=cgroup_root, enabled=False)
        is None
    )
    # Disabled env declines.
    monkeypatch.setenv("SASE_DETACH_SCOPE_DISABLE", "1")
    assert (
        _own_agent_scope(proc_root=proc_root, cgroup_root=cgroup_root, enabled=True)
        is None
    )
    monkeypatch.delenv("SASE_DETACH_SCOPE_DISABLE", raising=False)
    # Non-Linux declines.
    monkeypatch.setattr("sase.agent._scope_sweep_own.sys.platform", "darwin")
    assert (
        _own_agent_scope(proc_root=proc_root, cgroup_root=cgroup_root, enabled=True)
        is None
    )
    monkeypatch.setattr("sase.agent._scope_sweep_own.sys.platform", "linux")
    # Cgroup v1 declines.
    self_cgroup = proc_root / str(os.getpid()) / "cgroup"
    self_cgroup.write_text("2:cpu:/user.slice/sase-agent-1-2.scope\n", encoding="utf-8")
    assert (
        _own_agent_scope(proc_root=proc_root, cgroup_root=cgroup_root, enabled=True)
        is None
    )
    self_cgroup.write_text(_SCOPE_CGROUP, encoding="utf-8")
    # A non-agent unit declines.
    self_cgroup.write_text(
        "0::/user.slice/user-1000.slice/session-2.scope\n", encoding="utf-8"
    )
    assert (
        _own_agent_scope(proc_root=proc_root, cgroup_root=cgroup_root, enabled=True)
        is None
    )
    self_cgroup.write_text(_SCOPE_CGROUP, encoding="utf-8")
    # A non-runner argv declines (e.g. pytest inside the scope).
    (proc_root / str(os.getpid()) / "cmdline").write_bytes(b"pytest\0tests/\0")
    assert (
        _own_agent_scope(proc_root=proc_root, cgroup_root=cgroup_root, enabled=True)
        is None
    )


def test_sweep_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.agent._scope_sweep_own._own_agent_scope",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert sweep_own_agent_scope(context="exit") is None


def test_sweep_skipped_outside_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SASE_DETACH_SCOPE_DISABLE", raising=False)
    monkeypatch.setattr("sase.agent._scope_sweep_own.sys.platform", "win32")
    assert sweep_own_agent_scope(context="turn", enabled=True) is None


def test_execute_real_signal_only_targets_created_pids(tmp_path: Path) -> None:
    """End-to-end against the real /proc: only the test's own sleep dies."""
    proc = subprocess.Popen(["sleep", "300"])
    try:
        scope_dir = tmp_path / "scope"
        scope_dir.mkdir()
        (scope_dir / "cgroup.procs").write_text(f"{proc.pid}\n", encoding="utf-8")
        members = read_scope_members(scope_dir)
        assert [m.pid for m in members] == [proc.pid]
        plan = plan_scope_sweep(members, protect_root=None, spare_patterns=())
        assert [m.pid for m in plan.targets] == [proc.pid]
        result = execute_scope_sweep(plan, scope_dir, grace_seconds=0.2)
        assert proc.poll() is not None
        assert [m.pid for m in result.terminated] == [proc.pid]
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


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


def test_sweep_prints_summary_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proc_root = tmp_path / "proc"
    scope_dir, cgroup_root = _make_scope(tmp_path, [800], proc_root=proc_root)
    _write_proc(proc_root, 800, ["while", "loop"], ppid=1)
    monkeypatch.delenv("SASE_DETACH_SCOPE_DISABLE", raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    monkeypatch.setattr("sase.agent._scope_sweep_own.sys.platform", "linux")

    def fake_kill(pid: int, sig: int) -> None:
        # Simulate death: the next read finds no such process.
        (proc_root / str(pid) / "stat").unlink(missing_ok=True)

    monkeypatch.setattr(os, "kill", fake_kill)
    result = sweep_own_agent_scope(
        context="exit",
        proc_root=proc_root,
        cgroup_root=cgroup_root,
        enabled=True,
        grace_seconds=0,
        spare_patterns=(),
    )
    assert result is not None
    assert [m.pid for m in result.terminated] == [800]
    out = capsys.readouterr().out
    assert "[scope-sweep exit] terminated 1 leaked process(es)" in out
    assert _SCOPE_UNIT in out
