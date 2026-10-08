"""Sweep leaked processes out of an agent runner's own systemd scope.

Contract: an agent runner's ``sase-agent-*`` scope bounds the lifetime of
every process the agent starts. Work that must outlive the runner must escape
through :func:`sase.detach_scope.detach_scope` into its own scope. Anything
still in the scope that is not the runner, not one of the runner's live
descendants, and not a spared shared daemon is a leak and gets terminated.

The same pure selection rule (:func:`plan_scope_sweep`) is used at runner
exit, between in-process successor turns, and (in a later phase) by the
orphaned-scope reaper backstop.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

log = logging.getLogger(__name__)

#: Unit prefix for agent runner scopes (see ``agent/launch_spawn.py``).
AGENT_SCOPE_UNIT_PREFIX = "sase-agent"
#: Runner script basename identifying the live runner process.
RUNNER_SCRIPT_NAME = "run_agent_runner.py"

#: Default spare patterns (matched with ``re.search`` against comm or argv).
DEFAULT_SPARE_PROCESS_PATTERNS: tuple[str, ...] = (
    "^ssh-agent$",
    "^gpg-agent$",
    "^tmux: server$",
    r"^ssh: .*\[mux\]$",
)

#: Dead states skipped during member reads (zombies can no longer run).
_DEAD_STATES = frozenset({"Z", "X", "x"})
#: How many TERM/KILL rounds ``execute_scope_sweep`` runs at most.
_MAX_SWEEP_ROUNDS = 3
#: Poll interval while waiting out the TERM grace.
_SWEEP_POLL_SECONDS = 0.05
#: Hard cap past the grace for the whole sweep.
_SWEEP_OVERRUN_SECONDS = 5.0
#: Entries listed on the runner-output summary line.
_SWEEP_LOG_LIST_LIMIT = 10
#: Characters of argv shown per listed entry.
_SWEEP_ARGV_WIDTH = 120


@dataclass(frozen=True)
class ScopeMember:
    """One live process found in a scope's ``cgroup.procs``."""

    pid: int
    ppid: int
    comm: str
    argv: tuple[str, ...]
    identity: str


@dataclass(frozen=True)
class ScopeSweepPlan:
    """Pure selection result: what a sweep would signal."""

    targets: tuple[ScopeMember, ...]
    spared: tuple[ScopeMember, ...]
    protected: tuple[ScopeMember, ...]
    spare_patterns: tuple[str, ...] = ()
    protect_root_pid: int | None = None


@dataclass(frozen=True)
class ScopeSweepResult:
    """Outcome of :func:`execute_scope_sweep`."""

    unit: str
    terminated: tuple[ScopeMember, ...]
    survivors: tuple[ScopeMember, ...]
    rounds: int


def _read_stat_fields(proc_root: Path, pid: int) -> tuple[int, str, int] | None:
    """Return ``(ppid, state, start_ticks)`` for *pid*, or ``None``."""
    try:
        stat = (proc_root / str(pid) / "stat").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return None
    close_paren = stat.rfind(")")
    if close_paren < 0:
        return None
    parts = stat[close_paren + 1 :].split()
    try:
        state = parts[0]
        ppid = int(parts[1])
        start_ticks = int(parts[19])
    except (IndexError, ValueError):
        return None
    return ppid, state, start_ticks


def _identity_token(
    pid: int, start_ticks: int, *, proc_root: Path = Path("/proc")
) -> str:
    """Return an identity token pinning *pid* to its current incarnation."""
    if proc_root == Path("/proc"):
        from sase.core.process_identity import process_identity_token

        return process_identity_token(pid)
    try:
        boot_id = (
            Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        )
    except OSError:
        boot_id = ""
    return f"{boot_id}:{start_ticks}"


def _read_comm(proc_root: Path, pid: int) -> str | None:
    try:
        return (
            (proc_root / str(pid) / "comm")
            .read_text(encoding="utf-8", errors="replace")
            .strip()
        )
    except OSError:
        return None


def _read_argv(proc_root: Path, pid: int) -> tuple[str, ...] | None:
    try:
        data = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return None
    return tuple(
        part.decode("utf-8", errors="replace") for part in data.split(b"\0") if part
    )


def read_scope_members(
    scope_dir: Path, *, proc_root: Path = Path("/proc")
) -> list[ScopeMember]:
    """Return live members listed in ``scope_dir/cgroup.procs``.

    Zombies and unreadable pids are skipped.
    """
    try:
        procs = (scope_dir / "cgroup.procs").read_text(encoding="utf-8")
    except OSError:
        return []
    members: list[ScopeMember] = []
    for line in procs.splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        pid = int(line)
        stat = _read_stat_fields(proc_root, pid)
        if stat is None:
            continue
        ppid, state, start_ticks = stat
        if state in _DEAD_STATES:
            continue
        comm = _read_comm(proc_root, pid)
        if comm is None:
            continue
        argv = _read_argv(proc_root, pid)
        if argv is None:
            continue
        members.append(
            ScopeMember(
                pid=pid,
                ppid=ppid,
                comm=comm,
                argv=argv,
                identity=_identity_token(pid, start_ticks, proc_root=proc_root),
            )
        )
    return members


def is_agent_runner(member: ScopeMember) -> bool:
    """Whether *member* looks like the agent runner process."""
    for arg in member.argv[:3]:
        if PurePosixPath(arg).name == RUNNER_SCRIPT_NAME:
            return True
    return False


def _compile_spare_patterns(patterns: tuple[str, ...]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error:
            log.warning("Ignoring invalid spare process pattern %r", pattern)
    return compiled


def _descendants(roots: set[int], by_ppid: Mapping[int, list[int]]) -> set[int]:
    seen = set(roots)
    queue = list(roots)
    while queue:
        current = queue.pop()
        for child in by_ppid.get(current, ()):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return seen


def plan_scope_sweep(
    members: list[ScopeMember] | tuple[ScopeMember, ...],
    *,
    protect_root: ScopeMember | int | None,
    spare_patterns: tuple[str, ...] | list[str] = (),
) -> ScopeSweepPlan:
    """Apply the shared selection rule to *members*.

    The protect root (plus its live ``ppid`` descendants in the member set)
    is protected; members matching a spare pattern (plus their descendants)
    are spared; everything else is a target.
    """
    member_list = list(members)
    patterns = tuple(spare_patterns)
    by_pid = {member.pid: member for member in member_list}
    by_ppid: dict[int, list[int]] = {}
    for member in member_list:
        by_ppid.setdefault(member.ppid, []).append(member.pid)

    protected_ids: set[int] = set()
    root_pid: int | None = None
    if protect_root is not None:
        root_pid = (
            protect_root.pid if isinstance(protect_root, ScopeMember) else protect_root
        )
        if root_pid in by_pid:
            protected_ids = _descendants({root_pid}, by_ppid)

    compiled = _compile_spare_patterns(patterns)
    direct_spared = {
        member.pid
        for member in member_list
        if member.pid not in protected_ids
        and any(
            rx.search(member.comm) or rx.search(" ".join(member.argv))
            for rx in compiled
        )
    }
    spared_ids = _descendants(direct_spared, by_ppid) - protected_ids

    protected = tuple(m for m in member_list if m.pid in protected_ids)
    spared = tuple(m for m in member_list if m.pid in spared_ids)
    targets = tuple(
        m for m in member_list if m.pid not in protected_ids and m.pid not in spared_ids
    )
    return ScopeSweepPlan(
        targets=targets,
        spared=spared,
        protected=protected,
        spare_patterns=patterns,
        protect_root_pid=root_pid,
    )


def _identity_matches(
    pid: int, recorded: str, *, proc_root: Path = Path("/proc")
) -> bool:
    if proc_root == Path("/proc"):
        from sase.core.process_identity import process_identity_matches

        return process_identity_matches(pid, recorded)
    stat = _read_stat_fields(proc_root, pid)
    if stat is None:
        return False
    return _identity_token(pid, stat[2], proc_root=proc_root) == recorded


def _signal_targets(
    targets: tuple[ScopeMember, ...],
    sig: signal.Signals,
    *,
    proc_root: Path,
    kill: Callable[[int, int], None],
) -> list[ScopeMember]:
    signalled: list[ScopeMember] = []
    for target in targets:
        if not _identity_matches(target.pid, target.identity, proc_root=proc_root):
            continue
        try:
            kill(target.pid, sig)
        except OSError:
            continue
        signalled.append(target)
    return signalled


def _still_alive(member: ScopeMember, *, proc_root: Path = Path("/proc")) -> bool:
    stat = _read_stat_fields(proc_root, member.pid)
    if stat is None:
        return False
    if stat[1] in _DEAD_STATES:
        return False
    return _identity_matches(member.pid, member.identity, proc_root=proc_root)


def execute_scope_sweep(
    plan: ScopeSweepPlan,
    scope_dir: Path,
    *,
    grace_seconds: float = 3.0,
    proc_root: Path = Path("/proc"),
    kill: Callable[[int, int], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ScopeSweepResult:
    """SIGTERM then SIGKILL the plan's targets, re-reading for late arrivals.

    Up to 3 rounds; later rounds SIGKILL directly. The total run is bounded
    to the grace plus a small overrun.
    """
    kill_fn = os.kill if kill is None else kill
    unit = scope_dir.name
    grace = max(0.0, float(grace_seconds))
    deadline = clock() + grace + _SWEEP_OVERRUN_SECONDS
    terminated: list[ScopeMember] = []

    # Round 1: SIGTERM, wait out the grace, then SIGKILL the survivors.
    signalled = _signal_targets(
        tuple(plan.targets), signal.SIGTERM, proc_root=proc_root, kill=kill_fn
    )
    alive = list(signalled)
    grace_deadline = clock() + grace
    while alive and clock() < grace_deadline and clock() < deadline:
        sleep(_SWEEP_POLL_SECONDS)
        alive = [m for m in alive if _still_alive(m, proc_root=proc_root)]
    terminated.extend(signalled)
    terminated.extend(
        _signal_targets(tuple(alive), signal.SIGKILL, proc_root=proc_root, kill=kill_fn)
    )
    rounds = 1

    # Later rounds: members that appeared mid-sweep get SIGKILL directly.
    while rounds < _MAX_SWEEP_ROUNDS and clock() < deadline:
        fresh = read_scope_members(scope_dir, proc_root=proc_root)
        if not fresh:
            break
        replanned = plan_scope_sweep(
            fresh,
            protect_root=plan.protect_root_pid,
            spare_patterns=plan.spare_patterns,
        )
        if not replanned.targets:
            break
        rounds += 1
        terminated.extend(
            _signal_targets(
                replanned.targets, signal.SIGKILL, proc_root=proc_root, kill=kill_fn
            )
        )
        if rounds >= _MAX_SWEEP_ROUNDS:
            break
        # Brief settle so the next re-read sees who survived.
        settle_until = clock() + min(0.5, max(0.0, deadline - clock()))
        while clock() < settle_until:
            sleep(_SWEEP_POLL_SECONDS)

    # Deduplicate by pid, keeping first occurrence; survivors are re-checked.
    deduped: list[ScopeMember] = []
    seen: set[int] = set()
    for member in terminated:
        if member.pid not in seen:
            seen.add(member.pid)
            deduped.append(member)
    survivors_now = tuple(m for m in deduped if _still_alive(m, proc_root=proc_root))
    gone = tuple(m for m in deduped if m not in survivors_now)
    return ScopeSweepResult(
        unit=unit, terminated=gone, survivors=survivors_now, rounds=rounds
    )


def _own_cgroup_path(proc_root: Path) -> str | None:
    try:
        text = (proc_root / str(os.getpid()) / "cgroup").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[0] == "0" and fields[1] == "":
            return fields[2]
    return None


def _own_agent_scope(
    *,
    proc_root: Path = Path("/proc"),
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    enabled: bool | None = None,
) -> Path | None:
    """Return this runner's own scope cgroup dir, or ``None`` when no sweep.

    Every in-runner safety rail applies: Linux only, unified cgroup v2, own
    unit matches ``sase-agent-*.scope``, detach not disabled, config enabled,
    and the current process is the runner.
    """
    if sys.platform != "linux":
        return None
    cgroup_path = _own_cgroup_path(proc_root)
    if cgroup_path is None:
        return None
    from sase.detach_scope import detach_scope_disabled, unit_from_cgroup_path

    unit = unit_from_cgroup_path(cgroup_path)
    if (
        unit is None
        or not unit.startswith(AGENT_SCOPE_UNIT_PREFIX + "-")
        or not unit.endswith(".scope")
    ):
        return None
    if detach_scope_disabled():
        return None
    if enabled is None:
        try:
            from sase.config._settings_system import (
                get_agent_scope_teardown_enabled,
            )

            enabled = get_agent_scope_teardown_enabled()
        except Exception:  # noqa: BLE001 - sweep is best-effort.
            return None
    if not enabled:
        return None
    try:
        raw = (proc_root / str(os.getpid()) / "cmdline").read_bytes()
    except OSError:
        return None
    argv = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
    if not any(PurePosixPath(arg).name == RUNNER_SCRIPT_NAME for arg in argv):
        return None
    relative = cgroup_path.lstrip("/")
    scope_dir = cgroup_root / relative
    try:
        if not scope_dir.is_dir():
            return None
    except OSError:
        return None
    return scope_dir


def _format_entry(member: ScopeMember) -> str:
    argv = " ".join(member.argv)
    if len(argv) > _SWEEP_ARGV_WIDTH:
        argv = argv[:_SWEEP_ARGV_WIDTH]
    return f"{member.pid} {member.comm} {argv}".rstrip()


def sweep_own_agent_scope(
    *,
    context: Literal["exit", "turn"],
    proc_root: Path = Path("/proc"),
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    enabled: bool | None = None,
    grace_seconds: float | None = None,
    spare_patterns: tuple[str, ...] | list[str] | None = None,
) -> ScopeSweepResult | None:
    """Sweep this runner's own scope; never raises.

    Returns the sweep result, or ``None`` when the safety rails decline.
    """
    try:
        scope_dir = _own_agent_scope(
            proc_root=proc_root, cgroup_root=cgroup_root, enabled=enabled
        )
        if scope_dir is None:
            return None
        from sase.config._settings_system import (
            get_agent_scope_teardown_spare_process_patterns,
            get_agent_scope_teardown_term_grace_seconds,
        )

        patterns = (
            tuple(spare_patterns)
            if spare_patterns is not None
            else tuple(get_agent_scope_teardown_spare_process_patterns())
        )
        grace = (
            float(grace_seconds)
            if grace_seconds is not None
            else get_agent_scope_teardown_term_grace_seconds()
        )
        members = read_scope_members(scope_dir, proc_root=proc_root)
        plan = plan_scope_sweep(
            members, protect_root=os.getpid(), spare_patterns=patterns
        )
        if not plan.targets:
            return ScopeSweepResult(
                unit=scope_dir.name, terminated=(), survivors=(), rounds=1
            )
        result = execute_scope_sweep(
            plan, scope_dir, grace_seconds=grace, proc_root=proc_root
        )
        if result.terminated:
            entries = ", ".join(
                _format_entry(m) for m in result.terminated[:_SWEEP_LOG_LIST_LIMIT]
            )
            line = (
                f"[scope-sweep {context}] terminated "
                f"{len(result.terminated)} leaked process(es) "
                f"in {result.unit}: {entries}"
            )
            print(line)
            log.info("%s", line)
        return result
    except Exception:  # noqa: BLE001 - the sweep must never break the runner.
        log.exception("Agent scope sweep failed")
        return None


__all__ = [
    "AGENT_SCOPE_UNIT_PREFIX",
    "DEFAULT_SPARE_PROCESS_PATTERNS",
    "RUNNER_SCRIPT_NAME",
    "ScopeMember",
    "ScopeSweepPlan",
    "ScopeSweepResult",
    "execute_scope_sweep",
    "is_agent_runner",
    "plan_scope_sweep",
    "read_scope_members",
    "sweep_own_agent_scope",
]
