"""Unit tests for the orphaned agent-scope reaper backstop."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.agent._scope_sweep_reap import (
    _discover_agent_scopes,
    _parse_scope_created_ns,
    _user_manager_root,
)
from sase.agent.scope_sweep import reap_orphaned_agent_scopes

_NOW_NS = 1_700_000_000_000_000_000
_OLD_NS = _NOW_NS - 1_000_000_000_000  # 1000 s old
_YOUNG_NS = _NOW_NS - 10_000_000_000  # 10 s old


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
    environ: bytes | None = None,
) -> None:
    _write_stat(
        proc_root, pid, ppid=ppid, state=state, start_ticks=start_ticks, comm=comm
    )
    proc_dir = proc_root / str(pid)
    (proc_dir / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    if environ is not None:
        (proc_dir / "environ").write_bytes(environ)


def _write_self_cgroup(proc_root: Path) -> None:
    self_dir = proc_root / str(os.getpid())
    self_dir.mkdir(parents=True, exist_ok=True)
    (self_dir / "cgroup").write_text(
        "0::/user.slice/user-1000.slice/user@1000.service/app.slice/test.scope\n",
        encoding="utf-8",
    )
    _write_stat(proc_root, os.getpid(), ppid=1)


def _make_scope(
    cgroup_root: Path, unit: str, pids: list[int], *, proc_root: Path
) -> Path:
    scope_dir = cgroup_root / "app.slice" / unit
    scope_dir.mkdir(parents=True)
    (scope_dir / "cgroup.procs").write_text(
        "".join(f"{pid}\n" for pid in pids), encoding="utf-8"
    )
    _write_self_cgroup(proc_root)
    return scope_dir


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sase.agent._scope_sweep_reap.sys.platform", "linux")


def test_parse_scope_created_ns() -> None:
    assert _parse_scope_created_ns("sase-agent-999-1234567890.scope") == 1234567890
    assert _parse_scope_created_ns("sase-agent-999-0.scope") == 0
    assert _parse_scope_created_ns("sase-agent-999-latest.scope") is None
    assert _parse_scope_created_ns("sase-agent-noname.scope") is None
    assert _parse_scope_created_ns("other-1-2.scope") == 2


def test_user_manager_root_from_own_cgroup() -> None:
    text = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/x.scope\n"
    root = _user_manager_root(text, uid=1000)
    assert root == Path("/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service")


def test_user_manager_root_fallback() -> None:
    root = _user_manager_root(None, uid=4242)
    assert root == Path("/sys/fs/cgroup/user.slice/user-4242.slice/user@4242.service")
    root = _user_manager_root("2:cpu:/user.slice/session-2.scope\n", uid=4242)
    assert root == Path("/sys/fs/cgroup/user.slice/user-4242.slice/user@4242.service")


def test_discovery_depth_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch)
    proc_root = tmp_path / "proc"
    cgroup_root = tmp_path / "cgroup"
    shallow = cgroup_root / "app.slice" / f"sase-agent-1-{_OLD_NS}.scope"
    shallow.mkdir(parents=True)
    deep_parent = cgroup_root / "a" / "b" / "c" / "d"
    deep_parent.mkdir(parents=True)
    (deep_parent / f"sase-agent-2-{_OLD_NS}.scope").mkdir()
    (cgroup_root / "app.slice" / "other-1-2.scope").mkdir()
    _write_self_cgroup(proc_root)
    scopes = _discover_agent_scopes(cgroup_root=cgroup_root, proc_root=proc_root)
    assert [s.unit for s in scopes] == [f"sase-agent-1-{_OLD_NS}.scope"]


def test_discovery_only_units_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _linux(monkeypatch)
    proc_root = tmp_path / "proc"
    cgroup_root = tmp_path / "cgroup"
    for pid_ns in (11, 12):
        (cgroup_root / "app.slice" / f"sase-agent-{pid_ns}-{_OLD_NS}.scope").mkdir(
            parents=True
        )
    _write_self_cgroup(proc_root)
    scopes = _discover_agent_scopes(
        cgroup_root=cgroup_root,
        only_units={f"sase-agent-11-{_OLD_NS}.scope"},
        proc_root=proc_root,
    )
    assert [s.unit for s in scopes] == [f"sase-agent-11-{_OLD_NS}.scope"]


def test_pytest_guard_refuses_unfiltered_real_scan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _linux(monkeypatch)
    proc_root = tmp_path / "proc"
    _write_self_cgroup(proc_root)
    with pytest.raises(RuntimeError, match="explicit cgroup_root or only_units"):
        _discover_agent_scopes(proc_root=proc_root)


def test_pytest_guard_allows_explicit_filter_without_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _linux(monkeypatch)
    proc_root = tmp_path / "proc"
    _write_self_cgroup(proc_root)
    monkeypatch.setattr(
        "sase.agent._scope_sweep_reap._iter_scope_dirs",
        lambda _root, max_depth=3: [],
    )
    assert _discover_agent_scopes(only_units={"x.scope"}, proc_root=proc_root) == []


def _build_mixed_tree(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, str]]:
    proc_root = tmp_path / "proc"
    cgroup_root = tmp_path / "cgroup"
    units = {
        "young": f"sase-agent-11-{_YOUNG_NS}.scope",
        "unparsable": "sase-agent-12-latest.scope",
        "live": f"sase-agent-13-{_OLD_NS}.scope",
        "systemd_run": f"sase-agent-14-{_OLD_NS}.scope",
        "empty": f"sase-agent-15-{_OLD_NS}.scope",
        "spared": f"sase-agent-16-{_OLD_NS}.scope",
        "reapable": f"sase-agent-17-{_OLD_NS}.scope",
    }
    _write_proc(proc_root, 1101, ["busy-loop"], start_ticks=101)
    _make_scope(cgroup_root, units["young"], [1101], proc_root=proc_root)
    _write_proc(proc_root, 1201, ["busy-loop"], start_ticks=102)
    _make_scope(cgroup_root, units["unparsable"], [1201], proc_root=proc_root)
    _write_proc(proc_root, 1301, ["python", "run_agent_runner.py"], start_ticks=103)
    _write_proc(proc_root, 1302, ["busy-loop"], ppid=1301, start_ticks=104)
    _make_scope(cgroup_root, units["live"], [1301, 1302], proc_root=proc_root)
    _write_proc(
        proc_root,
        1401,
        ["systemd-run", "--user", "--scope", "sh"],
        comm="systemd-run",
        start_ticks=105,
    )
    _make_scope(cgroup_root, units["systemd_run"], [1401], proc_root=proc_root)
    _make_scope(cgroup_root, units["empty"], [], proc_root=proc_root)
    _write_proc(
        proc_root,
        1601,
        ["ssh-agent", "-a", "/tmp/sock"],
        comm="ssh-agent",
        start_ticks=106,
    )
    _make_scope(cgroup_root, units["spared"], [1601], proc_root=proc_root)
    _write_proc(
        proc_root,
        1701,
        ["busy-loop"],
        start_ticks=107,
        environ=b"SASE_AGENT_NAME=test-agent\x00OTHER=1\x00",
    )
    _make_scope(cgroup_root, units["reapable"], [1701], proc_root=proc_root)
    return proc_root, cgroup_root, units


def test_reap_classifies_every_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _linux(monkeypatch)
    proc_root, cgroup_root, units = _build_mixed_tree(tmp_path)
    clock = _Clock()
    result = reap_orphaned_agent_scopes(
        apply=False,
        min_age_seconds=120,
        cgroup_root=cgroup_root,
        proc_root=proc_root,
        spare_patterns=("^ssh-agent$",),
        now_ns=_NOW_NS,
        kill=lambda pid, sig: (_ for _ in ()).throw(AssertionError("must not signal")),
        clock=clock.clock,
        sleep=clock.sleep,
    )
    assert result.scanned == 7
    assert result.live == 2
    assert result.skipped_young == 2
    assert result.empty == 1
    assert result.spared_only == 1
    assert [s.unit for s in result.reaped] == [units["reapable"]]
    assert result.reaped[0].agent_name == "test-agent"
    assert result.reaped[0].targets == 1
    assert result.reaped[0].terminated == 0
    assert result.terminated == 0
    assert result.errors == 0


def test_reap_apply_true_signals_only_leaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _linux(monkeypatch)
    proc_root, cgroup_root, units = _build_mixed_tree(tmp_path)
    calls: list[tuple[int, int]] = []
    clock = _Clock()
    result = reap_orphaned_agent_scopes(
        apply=True,
        min_age_seconds=120,
        cgroup_root=cgroup_root,
        proc_root=proc_root,
        grace_seconds=0,
        spare_patterns=("^ssh-agent$",),
        now_ns=_NOW_NS,
        kill=lambda pid, sig: calls.append((pid, int(sig))),
        clock=clock.clock,
        sleep=clock.sleep,
    )
    signalled = {pid for pid, _ in calls}
    assert 1701 in signalled
    assert 1301 not in signalled
    assert 1302 not in signalled
    assert 1401 not in signalled
    assert 1601 not in signalled
    assert [s.unit for s in result.reaped] == [units["reapable"]]
    assert result.errors == 0


def test_reap_live_runner_with_leftovers_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _linux(monkeypatch)
    proc_root = tmp_path / "proc"
    cgroup_root = tmp_path / "cgroup"
    unit = f"sase-agent-21-{_OLD_NS}.scope"
    _write_proc(proc_root, 2101, ["python", "run_agent_runner.py"], start_ticks=201)
    _write_proc(proc_root, 2102, ["busy-loop"], ppid=1, start_ticks=202)
    _make_scope(cgroup_root, unit, [2101, 2102], proc_root=proc_root)
    calls: list[tuple[int, int]] = []
    clock = _Clock()
    result = reap_orphaned_agent_scopes(
        apply=True,
        min_age_seconds=0,
        cgroup_root=cgroup_root,
        proc_root=proc_root,
        grace_seconds=0,
        now_ns=_NOW_NS,
        kill=lambda pid, sig: calls.append((pid, int(sig))),
        clock=clock.clock,
        sleep=clock.sleep,
    )
    assert result.live == 1
    assert result.reaped == ()
    assert calls == []
    assert result.terminated == 0


def test_reap_agent_name_missing_when_no_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _linux(monkeypatch)
    proc_root = tmp_path / "proc"
    cgroup_root = tmp_path / "cgroup"
    unit = f"sase-agent-22-{_OLD_NS}.scope"
    _write_proc(proc_root, 2201, ["busy-loop"], start_ticks=301)
    _make_scope(cgroup_root, unit, [2201], proc_root=proc_root)
    clock = _Clock()
    result = reap_orphaned_agent_scopes(
        apply=False,
        min_age_seconds=0,
        cgroup_root=cgroup_root,
        proc_root=proc_root,
        now_ns=_NOW_NS,
        clock=clock.clock,
        sleep=clock.sleep,
    )
    assert len(result.reaped) == 1
    assert result.reaped[0].agent_name is None


def test_reap_refuses_unfiltered_scan_under_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _linux(monkeypatch)
    proc_root = tmp_path / "proc"
    _write_self_cgroup(proc_root)
    with pytest.raises(RuntimeError, match="explicit cgroup_root or only_units"):
        reap_orphaned_agent_scopes(apply=False, proc_root=proc_root)


def test_reap_non_linux_returns_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("sase.agent._scope_sweep_reap.sys.platform", "darwin")
    result = reap_orphaned_agent_scopes(apply=False)
    assert result.reason == "not_linux"
    assert result.scanned == 0


def test_reap_counts_scope_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.agent._scope_sweep_reap as sweep

    _linux(monkeypatch)
    proc_root = tmp_path / "proc"
    cgroup_root = tmp_path / "cgroup"
    good = f"sase-agent-31-{_OLD_NS}.scope"
    bad = f"sase-agent-32-{_OLD_NS}.scope"
    _write_proc(proc_root, 3101, ["busy-loop"], start_ticks=401)
    _make_scope(cgroup_root, good, [3101], proc_root=proc_root)
    bad_dir = cgroup_root / "app.slice" / bad
    bad_dir.mkdir(parents=True)
    (bad_dir / "cgroup.procs").write_text("3101\n", encoding="utf-8")
    _write_self_cgroup(proc_root)
    real_reader = sweep.read_scope_members

    def flaky_reader(scope_dir: Path, *, proc_root: Path = Path("/proc")):
        if scope_dir.name == bad:
            raise RuntimeError("boom")
        return real_reader(scope_dir, proc_root=proc_root)

    monkeypatch.setattr(sweep, "read_scope_members", flaky_reader)
    clock = _Clock()
    result = reap_orphaned_agent_scopes(
        apply=False,
        min_age_seconds=0,
        cgroup_root=cgroup_root,
        proc_root=proc_root,
        now_ns=_NOW_NS,
        clock=clock.clock,
        sleep=clock.sleep,
    )
    assert result.errors == 1
    assert [s.unit for s in result.reaped] == [good]
