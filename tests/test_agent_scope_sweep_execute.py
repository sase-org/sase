"""Scope-sweep execution tests (identity pinning, grace escalation, signals).

Split from ``tests.test_agent_scope_sweep``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path

from sase.agent._scope_sweep_core import (
    execute_scope_sweep,
    plan_scope_sweep,
    read_scope_members,
)
from tests._agent_scope_sweep_helpers import write_proc


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps = 0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds


def test_execute_identity_pinning_skips_recycled_pid(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    scope_dir = tmp_path / "scope"
    scope_dir.mkdir()
    write_proc(proc_root, 400, ["busy-loop"], start_ticks=100)
    (scope_dir / "cgroup.procs").write_text("400\n", encoding="utf-8")
    members = read_scope_members(scope_dir, proc_root=proc_root)
    assert len(members) == 1
    plan = plan_scope_sweep(members, protect_root=None, spare_patterns=())
    assert [m.pid for m in plan.targets] == [400]
    # The target exits and its pid is recycled by a process outside the
    # scope: the scope no longer lists it, and its start time changed.
    write_proc(proc_root, 400, ["innocent"], start_ticks=999)
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
    write_proc(proc_root, 500, ["busy-loop"])
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
    write_proc(proc_root, 600, ["first"])
    (scope_dir / "cgroup.procs").write_text("600\n", encoding="utf-8")
    members = read_scope_members(scope_dir, proc_root=proc_root)
    plan = plan_scope_sweep(members, protect_root=None, spare_patterns=())

    calls: list[tuple[int, int]] = []
    clock = _Clock()

    def fake_kill(pid: int, sig: int) -> None:
        calls.append((pid, int(sig)))
        if pid == 600 and int(sig) == int(signal.SIGTERM):
            # A second leak appears mid-sweep, after the TERM round.
            write_proc(proc_root, 601, ["late"])
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
