"""Scope-sweep planning tests (protect roots, spare patterns, member reads).

Split from ``tests.test_agent_scope_sweep``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

from sase.agent._scope_sweep_core import (
    is_agent_runner,
    plan_scope_sweep,
    read_scope_members,
)
from sase.agent._scope_sweep_types import ScopeMember
from tests._agent_scope_sweep_helpers import write_proc, write_stat


def _member(
    pid: int, ppid: int = 1, comm: str = "sh", argv: tuple[str, ...] = ("sh",)
) -> ScopeMember:
    return ScopeMember(pid=pid, ppid=ppid, comm=comm, argv=argv, identity=f"boot:{pid}")


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
    write_proc(proc_root, 300, ["sleep", "10"])
    write_proc(proc_root, 301, ["sleep", "10"], state="Z")
    write_stat(proc_root, 302, ppid=1)  # no comm/cmdline: unreadable
    (scope_dir / "cgroup.procs").write_text("300\n301\n302\n999\n", encoding="utf-8")
    members = read_scope_members(scope_dir, proc_root=proc_root)
    assert [m.pid for m in members] == [300]
    assert members[0].argv == ("sleep", "10")


def test_invalid_spare_regex_is_ignored() -> None:
    leak = _member(700)
    plan = plan_scope_sweep([leak], protect_root=None, spare_patterns=("[bad",))
    assert [m.pid for m in plan.targets] == [700]
