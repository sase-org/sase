"""Shared fixtures for the ``test_agent_scope_sweep_*`` test modules.

Split from ``tests.test_agent_scope_sweep``; the original module re-exports
its tests so its import path keeps working.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_agent_scope_sweep_*`` split modules can share them
without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from pathlib import Path

from sase.agent.scope_sweep import AGENT_SCOPE_UNIT_PREFIX

__all__ = [
    "SCOPE_CGROUP",
    "SCOPE_UNIT",
    "write_proc",
    "write_stat",
]

SCOPE_UNIT = f"{AGENT_SCOPE_UNIT_PREFIX}-999-1234567890.scope"
SCOPE_CGROUP = (
    "0::/user.slice/user-1000.slice/user@1000.service/app.slice/" + SCOPE_UNIT + "\n"
)


def write_stat(
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


def write_proc(
    proc_root: Path,
    pid: int,
    argv: list[str],
    *,
    ppid: int = 1,
    state: str = "S",
    start_ticks: int = 1000,
    comm: str | None = None,
) -> None:
    write_stat(
        proc_root, pid, ppid=ppid, state=state, start_ticks=start_ticks, comm=comm
    )
    proc_dir = proc_root / str(pid)
    (proc_dir / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (proc_dir / "cgroup").write_text(SCOPE_CGROUP, encoding="utf-8")
