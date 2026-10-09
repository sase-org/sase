"""Own-scope gating and sweep entry tests.

Split from ``tests.test_agent_scope_sweep``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.agent._scope_sweep_own import _own_agent_scope
from sase.agent.scope_sweep import RUNNER_SCRIPT_NAME, sweep_own_agent_scope
from tests._agent_scope_sweep_helpers import (
    SCOPE_CGROUP,
    SCOPE_UNIT,
    write_proc,
    write_stat,
)


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
        / SCOPE_UNIT
    )
    scope_dir.mkdir(parents=True)
    (scope_dir / "cgroup.procs").write_text(
        "".join(f"{pid}\n" for pid in pids), encoding="utf-8"
    )
    self_dir = proc_root / str(os.getpid())
    self_dir.mkdir(parents=True, exist_ok=True)
    (self_dir / "cgroup").write_text(SCOPE_CGROUP, encoding="utf-8")
    (self_dir / "cmdline").write_bytes(
        b"python\0/opt/sase/src/sase/axe/" + RUNNER_SCRIPT_NAME.encode() + b"\0"
    )
    write_stat(proc_root, os.getpid(), ppid=1)
    return scope_dir, cgroup_root


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
    self_cgroup.write_text(SCOPE_CGROUP, encoding="utf-8")
    # A non-agent unit declines.
    self_cgroup.write_text(
        "0::/user.slice/user-1000.slice/session-2.scope\n", encoding="utf-8"
    )
    assert (
        _own_agent_scope(proc_root=proc_root, cgroup_root=cgroup_root, enabled=True)
        is None
    )
    self_cgroup.write_text(SCOPE_CGROUP, encoding="utf-8")
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


def test_sweep_prints_summary_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proc_root = tmp_path / "proc"
    scope_dir, cgroup_root = _make_scope(tmp_path, [800], proc_root=proc_root)
    write_proc(proc_root, 800, ["while", "loop"], ppid=1)
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
    assert SCOPE_UNIT in out
