"""UI-free ``/proc`` discovery of every process that belongs to one agent.

A runner's process group is only part of its process set: inline
``sase tool run`` children and runner helpers start their own sessions, and
provider CLIs leak session leaders that outlive the runner. Four independent
signals find them:

* the process group and the session whose id is the runner pid (session
  members outlive the leader, and the kernel never recycles a pid that is
  still a live group or session id, so these matches stay valid after the
  runner itself is gone);
* the ``SASE_LAUNCH_SCRATCH_KEY`` the launcher put in the runner's
  environment, which every descendant inherits no matter how it detached;
* the ``ppid`` tree below the runner and the processes found above.

Discovery reads ``/proc`` directly. Platforms without ``/proc`` return an
empty table, and callers fall back to signalling the recorded pid's group.
"""

from __future__ import annotations

import os
from collections import defaultdict, deque
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from sase.env_contracts import SASE_LAUNCH_SCRATCH_KEY_ENV

PROC_ROOT = Path("/proc")

# A zombie has already exited and only awaits its parent's ``wait``; it can no
# longer run anything, so it counts as dead for termination.
_DEAD_STATES = frozenset({"Z", "X", "x"})

REASON_RUNNER = "runner"
REASON_GROUP = "group"
REASON_SESSION = "session"
REASON_SCRATCH_KEY = "scratch_key"
REASON_DESCENDANT = "descendant"


@dataclass(frozen=True)
class ProcessRow:
    """One ``/proc/<pid>/stat`` row."""

    pid: int
    ppid: int
    pgid: int
    sid: int
    state: str

    @property
    def is_dead(self) -> bool:
        return self.state in _DEAD_STATES


def proc_available() -> bool:
    """Whether ``/proc`` can be enumerated on this platform."""
    return PROC_ROOT.is_dir()


def read_process_row(pid: int) -> ProcessRow | None:
    """Return the stat row for *pid*, or ``None`` when it does not exist."""
    try:
        stat = (PROC_ROOT / str(pid) / "stat").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return None
    # ``comm`` may itself contain parentheses; the last one closes it.
    close_paren = stat.rfind(")")
    if close_paren < 0:
        return None
    fields = stat[close_paren + 1 :].split()
    try:
        return ProcessRow(
            pid=pid,
            state=fields[0],
            ppid=int(fields[1]),
            pgid=int(fields[2]),
            sid=int(fields[3]),
        )
    except (IndexError, ValueError):
        return None


def read_process_table() -> dict[int, ProcessRow]:
    """Snapshot every visible process, or ``{}`` when ``/proc`` is unusable."""
    try:
        names = os.listdir(PROC_ROOT)
    except OSError:
        return {}
    table: dict[int, ProcessRow] = {}
    for name in names:
        if not name.isdigit():
            continue
        row = read_process_row(int(name))
        if row is not None:
            table[row.pid] = row
    return table


def process_is_running(pid: int) -> bool:
    """Whether *pid* names a process that has not exited (zombies have)."""
    row = read_process_row(pid)
    if row is not None:
        return not row.is_dead
    if proc_available():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def environ_has_launch_key(pid: int, scratch_key: str) -> bool:
    """Whether *pid* was launched with ``SASE_LAUNCH_SCRATCH_KEY=<scratch_key>``.

    ``/proc/<pid>/environ`` is the environment the process started with, which
    is exactly what descendants inherit. Unreadable environments (another
    user's process, a process that just exited) never match.
    """
    try:
        data = (PROC_ROOT / str(pid) / "environ").read_bytes()
    except OSError:
        return False
    needle = f"{SASE_LAUNCH_SCRATCH_KEY_ENV}={scratch_key}".encode()
    return needle in data.split(b"\0")


def shielded_pids(
    table: Mapping[int, ProcessRow],
    *,
    extra: Collection[int] = (),
) -> frozenset[int]:
    """Return the pids that must never be signalled.

    That is the current process and every ancestor: the process doing the
    terminating (the durable cleanup proc, a CLI, a TUI) must not take itself
    down, and neither may the supervisors that own it. *extra* adds
    caller-protected pids.
    """
    shielded = {0, 1, os.getpid(), *extra}
    current = os.getpid()
    seen: set[int] = set()
    while current > 1 and current not in seen:
        seen.add(current)
        shielded.add(current)
        row = table.get(current)
        current = row.ppid if row is not None else 0
    shielded.add(os.getppid())
    return frozenset(shielded)


def descendants_of(
    seeds: Collection[int],
    table: Mapping[int, ProcessRow],
    *,
    skip: Collection[int] = (),
) -> list[int]:
    """Return live ``ppid`` descendants of *seeds*, never descending below *skip*."""
    children: dict[int, list[int]] = defaultdict(list)
    for row in table.values():
        children[row.ppid].append(row.pid)
    skipped = set(skip)
    seen = set(seeds)
    found: list[int] = []
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        for child in children.get(current, ()):
            if child in seen or child in skipped:
                continue
            seen.add(child)
            row = table[child]
            if not row.is_dead:
                found.append(child)
            queue.append(child)
    return found


def discover_strong_members(
    root_pid: int,
    table: Mapping[int, ProcessRow],
    *,
    scratch_key: str | None,
    trust_root_pid: bool,
    shielded: Collection[int],
) -> dict[int, str]:
    """Map pid -> reason for processes in the agent's group, session, or scratch.

    *trust_root_pid* says the pid still names the original runner (or nothing
    at all). It is false when the pid was recycled for an unrelated process,
    in which case the recycled process and its group say nothing about the
    agent and only the launch scratch key can identify its processes.
    """
    found: dict[int, str] = {}
    for row in table.values():
        pid = row.pid
        if row.is_dead or pid in shielded:
            continue
        if trust_root_pid:
            if pid == root_pid:
                found[pid] = REASON_RUNNER
                continue
            if row.pgid == root_pid:
                found[pid] = REASON_GROUP
                continue
            if row.sid == root_pid:
                found[pid] = REASON_SESSION
                continue
        if scratch_key and environ_has_launch_key(pid, scratch_key):
            found[pid] = REASON_SCRATCH_KEY
    return found


def discover_weak_members(
    root_pid: int,
    strong: Collection[int],
    table: Mapping[int, ProcessRow],
    *,
    trust_root_pid: bool,
    protected: Collection[int],
) -> list[int]:
    """Return ``ppid`` descendants of the runner and of the strong members.

    These carry no group, session, or scratch evidence of their own, so the
    caller must pass every pid that legitimately belongs to something else
    (registered agents, procs, the terminating process) as *protected*: those
    are neither returned nor descended into.
    """
    seeds = set(strong)
    if trust_root_pid:
        seeds.add(root_pid)
    skip = set(protected) - seeds
    return [
        pid
        for pid in descendants_of(seeds, table, skip=skip)
        if pid not in strong and pid not in protected
    ]


__all__ = [
    "ProcessRow",
    "REASON_DESCENDANT",
    "REASON_GROUP",
    "REASON_RUNNER",
    "REASON_SCRATCH_KEY",
    "REASON_SESSION",
    "descendants_of",
    "discover_strong_members",
    "discover_weak_members",
    "environ_has_launch_key",
    "proc_available",
    "process_is_running",
    "read_process_row",
    "read_process_table",
    "shielded_pids",
]
