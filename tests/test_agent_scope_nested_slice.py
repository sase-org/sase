"""Scope sweeps keep working when ``agent_scope.slice`` nests agent scopes.

With ``agent_scope.slice: sase-agents.slice`` systemd places agent scopes at
``user@<uid>.service/sase.slice/sase-agents.slice/<scope>`` instead of
``user@<uid>.service/app.slice/<scope>``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from sase.agent._scope_sweep_own import _own_agent_scope
from sase.agent._scope_sweep_reap import _discover_agent_scopes, _discovery_depth
from sase.agent.scope_sweep import (
    RUNNER_SCRIPT_NAME,
    reap_orphaned_agent_scopes,
    sweep_own_agent_scope,
)
from sase.detach_scope import unit_from_cgroup_path
from tests._agent_scope_sweep_helpers import write_proc, write_stat

_NOW_NS = 1_700_000_000_000_000_000
_OLD_NS = _NOW_NS - 1_000_000_000_000
_MANAGER = ("user.slice", "user-1000.slice", "user@1000.service")
_NESTED = ("sase.slice", "sase-agents.slice")


def _configure_slice(monkeypatch: pytest.MonkeyPatch, slice_name: str | None) -> None:
    config: dict[str, Any] = {"agent_scope": {"slice": slice_name}}
    monkeypatch.setattr("sase.config._settings_system._merged_config", lambda: config)


def _linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sase.agent._scope_sweep_reap.sys.platform", "linux")
    monkeypatch.setattr("sase.agent._scope_sweep_own.sys.platform", "linux")


def _write_self(proc_root: Path, cgroup_path: str, *, runner: bool = False) -> None:
    self_dir = proc_root / str(os.getpid())
    self_dir.mkdir(parents=True, exist_ok=True)
    (self_dir / "cgroup").write_text(f"0::{cgroup_path}\n", encoding="utf-8")
    if runner:
        (self_dir / "cmdline").write_bytes(
            b"python\0/opt/sase/src/sase/axe/" + RUNNER_SCRIPT_NAME.encode() + b"\0"
        )
    write_stat(proc_root, os.getpid(), ppid=1)


def _make_scope(
    base: Path, parents: tuple[str, ...], unit: str, pids: list[int]
) -> Path:
    scope_dir = base.joinpath(*parents, unit)
    scope_dir.mkdir(parents=True)
    (scope_dir / "cgroup.procs").write_text(
        "".join(f"{pid}\n" for pid in pids), encoding="utf-8"
    )
    return scope_dir


def test_discovery_depth_follows_configured_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_slice(monkeypatch, None)
    assert _discovery_depth() == 3
    assert _discovery_depth("sase-agents.slice") == 3
    assert _discovery_depth("a-b-c.slice") == 4
    _configure_slice(monkeypatch, "a-b-c-d.slice")
    assert _discovery_depth() == 5


def test_discovery_finds_nested_and_legacy_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _linux(monkeypatch)
    _configure_slice(monkeypatch, "sase-agents.slice")
    proc_root = tmp_path / "proc"
    manager_root = tmp_path / "cgroup"
    nested = f"sase-agent-1-{_OLD_NS}.scope"
    legacy = f"sase-agent-2-{_OLD_NS}.scope"
    _make_scope(manager_root, _NESTED, nested, [])
    _make_scope(manager_root, ("app.slice",), legacy, [])
    _write_self(proc_root, "/user.slice/user-1000.slice/user@1000.service/x.scope")

    scopes = _discover_agent_scopes(cgroup_root=manager_root, proc_root=proc_root)

    assert sorted(s.unit for s in scopes) == sorted([nested, legacy])
    by_unit = {s.unit: s.path for s in scopes}
    assert by_unit[nested] == manager_root.joinpath(*_NESTED, nested)


def test_discovery_reaches_deeper_configured_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _linux(monkeypatch)
    proc_root = tmp_path / "proc"
    manager_root = tmp_path / "cgroup"
    deep = f"sase-agent-3-{_OLD_NS}.scope"
    _make_scope(manager_root, ("a.slice", "a-b.slice", "a-b-c.slice"), deep, [])
    _write_self(proc_root, "/user.slice/user-1000.slice/user@1000.service/x.scope")

    _configure_slice(monkeypatch, None)
    assert _discover_agent_scopes(cgroup_root=manager_root, proc_root=proc_root) == []
    _configure_slice(monkeypatch, "a-b-c.slice")
    found = _discover_agent_scopes(cgroup_root=manager_root, proc_root=proc_root)
    assert [s.unit for s in found] == [deep]


def test_reaper_sweeps_orphan_in_nested_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _linux(monkeypatch)
    _configure_slice(monkeypatch, "sase-agents.slice")
    proc_root = tmp_path / "proc"
    manager_root = tmp_path / "cgroup"
    unit = f"sase-agent-4-{_OLD_NS}.scope"
    _make_scope(manager_root, _NESTED, unit, [4100])
    write_proc(proc_root, 4100, ["sleep", "1000"])
    _write_self(proc_root, "/user.slice/user-1000.slice/user@1000.service/x.scope")
    killed: list[tuple[int, int]] = []
    now = [1000.0]

    def advance(seconds: float) -> None:
        now[0] += seconds

    result = reap_orphaned_agent_scopes(
        apply=True,
        min_age_seconds=120,
        cgroup_root=manager_root,
        proc_root=proc_root,
        grace_seconds=0,
        spare_patterns=(),
        now_ns=_NOW_NS,
        kill=lambda pid, sig: killed.append((pid, sig)),
        clock=lambda: now[0],
        sleep=advance,
    )

    assert result.scanned == 1
    assert [scope.unit for scope in result.reaped] == [unit]
    assert {pid for pid, _ in killed} == {4100}


def test_own_sweep_resolves_nested_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _linux(monkeypatch)
    monkeypatch.delenv("SASE_DETACH_SCOPE_DISABLE", raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    proc_root = tmp_path / "proc"
    cgroup_root = tmp_path / "cgroup"
    unit = "sase-agent-999-1234567890.scope"
    scope_dir = _make_scope(cgroup_root, (*_MANAGER, *_NESTED), unit, [os.getpid()])
    cgroup_path = "/" + "/".join((*_MANAGER, *_NESTED, unit))
    _write_self(proc_root, cgroup_path, runner=True)

    assert unit_from_cgroup_path(cgroup_path) == unit
    assert (
        _own_agent_scope(proc_root=proc_root, cgroup_root=cgroup_root, enabled=True)
        == scope_dir
    )
    result = sweep_own_agent_scope(
        context="exit",
        proc_root=proc_root,
        cgroup_root=cgroup_root,
        enabled=True,
        grace_seconds=0,
        spare_patterns=(),
    )
    assert result is not None
    assert result.unit == unit
    assert result.terminated == ()
