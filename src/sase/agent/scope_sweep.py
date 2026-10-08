"""Sweep leaked processes out of an agent runner's own systemd scope.

Contract: an agent runner's ``sase-agent-*`` scope bounds the lifetime of
every process the agent starts. Work that must outlive the runner must escape
through :func:`sase.detach_scope.detach_scope` into its own scope. Anything
still in the scope that is not the runner, not one of the runner's live
descendants, and not a spared shared daemon is a leak and gets terminated.

The same pure selection rule (:func:`_plan_scope_sweep`) is used at runner
exit, between in-process successor turns, and by the orphaned-scope reaper
backstop (:func:`reap_orphaned_agent_scopes`).
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
#: How many TERM/KILL rounds ``_execute_scope_sweep`` runs at most.
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
class _ScopeMember:
    """One live process found in a scope's ``cgroup.procs``."""

    pid: int
    ppid: int
    comm: str
    argv: tuple[str, ...]
    identity: str


@dataclass(frozen=True)
class _ScopeSweepPlan:
    """Pure selection result: what a sweep would signal."""

    targets: tuple[_ScopeMember, ...]
    spared: tuple[_ScopeMember, ...]
    protected: tuple[_ScopeMember, ...]
    spare_patterns: tuple[str, ...] = ()
    protect_root_pid: int | None = None


@dataclass(frozen=True)
class _ScopeSweepResult:
    """Outcome of :func:`_execute_scope_sweep`."""

    unit: str
    terminated: tuple[_ScopeMember, ...]
    survivors: tuple[_ScopeMember, ...]
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


def _read_scope_members(
    scope_dir: Path, *, proc_root: Path = Path("/proc")
) -> list[_ScopeMember]:
    """Return live members listed in ``scope_dir/cgroup.procs``.

    Zombies and unreadable pids are skipped.
    """
    try:
        procs = (scope_dir / "cgroup.procs").read_text(encoding="utf-8")
    except OSError:
        return []
    members: list[_ScopeMember] = []
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
            _ScopeMember(
                pid=pid,
                ppid=ppid,
                comm=comm,
                argv=argv,
                identity=_identity_token(pid, start_ticks, proc_root=proc_root),
            )
        )
    return members


def _is_agent_runner(member: _ScopeMember) -> bool:
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


def _plan_scope_sweep(
    members: list[_ScopeMember] | tuple[_ScopeMember, ...],
    *,
    protect_root: _ScopeMember | int | None,
    spare_patterns: tuple[str, ...] | list[str] = (),
) -> _ScopeSweepPlan:
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
            protect_root.pid if isinstance(protect_root, _ScopeMember) else protect_root
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
    return _ScopeSweepPlan(
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
    targets: tuple[_ScopeMember, ...],
    sig: signal.Signals,
    *,
    proc_root: Path,
    kill: Callable[[int, int], None],
) -> list[_ScopeMember]:
    signalled: list[_ScopeMember] = []
    for target in targets:
        if not _identity_matches(target.pid, target.identity, proc_root=proc_root):
            continue
        try:
            kill(target.pid, sig)
        except OSError:
            continue
        signalled.append(target)
    return signalled


def _still_alive(member: _ScopeMember, *, proc_root: Path = Path("/proc")) -> bool:
    stat = _read_stat_fields(proc_root, member.pid)
    if stat is None:
        return False
    if stat[1] in _DEAD_STATES:
        return False
    return _identity_matches(member.pid, member.identity, proc_root=proc_root)


def _execute_scope_sweep(
    plan: _ScopeSweepPlan,
    scope_dir: Path,
    *,
    grace_seconds: float = 3.0,
    proc_root: Path = Path("/proc"),
    kill: Callable[[int, int], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> _ScopeSweepResult:
    """SIGTERM then SIGKILL the plan's targets, re-reading for late arrivals.

    Up to 3 rounds; later rounds SIGKILL directly. The total run is bounded
    to the grace plus a small overrun.
    """
    kill_fn = os.kill if kill is None else kill
    unit = scope_dir.name
    grace = max(0.0, float(grace_seconds))
    deadline = clock() + grace + _SWEEP_OVERRUN_SECONDS
    terminated: list[_ScopeMember] = []

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
        fresh = _read_scope_members(scope_dir, proc_root=proc_root)
        if not fresh:
            break
        replanned = _plan_scope_sweep(
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
    deduped: list[_ScopeMember] = []
    seen: set[int] = set()
    for member in terminated:
        if member.pid not in seen:
            seen.add(member.pid)
            deduped.append(member)
    survivors_now = tuple(m for m in deduped if _still_alive(m, proc_root=proc_root))
    gone = tuple(m for m in deduped if m not in survivors_now)
    return _ScopeSweepResult(
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


def _format_entry(member: _ScopeMember) -> str:
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
) -> _ScopeSweepResult | None:
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
        members = _read_scope_members(scope_dir, proc_root=proc_root)
        plan = _plan_scope_sweep(
            members, protect_root=os.getpid(), spare_patterns=patterns
        )
        if not plan.targets:
            return _ScopeSweepResult(
                unit=scope_dir.name, terminated=(), survivors=(), rounds=1
            )
        result = _execute_scope_sweep(
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


#: Basename identifying the pre-exec ``systemd-run`` window.
_SYSTEMD_RUN_BASENAME = "systemd-run"
#: How deep below the user-manager root scope discovery descends.
_REAPER_MAX_DISCOVERY_DEPTH = 3
#: Per-scope entries recorded for a reaped scope.
_REAPER_ENTRY_LIMIT = 5
#: Message when a pytest process attempts an unfiltered real-tree scan.
_REAPER_PYTEST_GUARD_MESSAGE = (
    "Refusing unfiltered orphaned-scope scan of the real cgroup tree "
    "from a pytest process: pass an explicit cgroup_root or only_units."
)


@dataclass(frozen=True)
class _AgentScope:
    """One ``sase-agent-*.scope`` directory found under the user manager."""

    unit: str
    path: Path
    created_ns: int | None


@dataclass(frozen=True)
class _ReapedScope:
    """Per-scope detail recorded for a reapable orphaned scope."""

    unit: str
    agent_name: str | None
    targets: int
    terminated: int
    entries: tuple[str, ...]


@dataclass(frozen=True)
class _ReapResult:
    """Outcome of :func:`reap_orphaned_agent_scopes`."""

    scanned: int
    live: int
    skipped_young: int
    empty: int
    spared_only: int
    reaped: tuple[_ReapedScope, ...]
    terminated: int
    errors: int
    reason: str | None = None

    @property
    def reaped_scopes(self) -> int:
        """Number of reapable scopes found."""
        return len(self.reaped)


def _parse_scope_created_ns(unit: str) -> int | None:
    """Return the trailing ``<time_ns>`` from a scope unit name, or ``None``."""
    name = unit
    if name.endswith(".scope"):
        name = name[: -len(".scope")]
    tail = name.rsplit("-", 1)[-1] if "-" in name else ""
    if tail.isdigit():
        try:
            return int(tail)
        except ValueError:
            return None
    return None


def _is_agent_scope_name(name: str) -> bool:
    return name.startswith(AGENT_SCOPE_UNIT_PREFIX + "-") and name.endswith(".scope")


def _is_systemd_run_member(member: _ScopeMember) -> bool:
    if member.comm == _SYSTEMD_RUN_BASENAME:
        return True
    return any(
        PurePosixPath(arg).name == _SYSTEMD_RUN_BASENAME for arg in member.argv[:3]
    )


def _cgroup_v2_unified(*, proc_root: Path = Path("/proc")) -> bool:
    try:
        text = (proc_root / str(os.getpid()) / "cgroup").read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[0] == "0" and fields[1] == "":
            return True
    return False


def _own_cgroup_text(*, proc_root: Path = Path("/proc")) -> str | None:
    try:
        return (proc_root / str(os.getpid()) / "cgroup").read_text(encoding="utf-8")
    except OSError:
        return None


def _user_manager_root(
    cgroup_text: str | None, *, uid: int, cgroup_base: Path = Path("/sys/fs/cgroup")
) -> Path:
    """Resolve the ``user@<uid>.service`` subtree from own cgroup text."""
    if cgroup_text:
        for line in cgroup_text.splitlines():
            fields = line.split(":", 2)
            path = fields[2] if len(fields) == 3 else line
            components = [part for part in path.split("/") if part]
            for index, component in enumerate(components):
                if component == f"user@{uid}.service":
                    return cgroup_base.joinpath(*components[: index + 1])
    return cgroup_base / "user.slice" / f"user-{uid}.slice" / f"user@{uid}.service"


def _iter_scope_dirs(search_root: Path, *, max_depth: int = 3) -> list[Path]:
    """Return ``sase-agent-*.scope`` directories at most *max_depth* deep."""
    found: list[Path] = []
    try:
        if not search_root.is_dir():
            return []
    except OSError:
        return []
    # Breadth-first walk bounded by depth; never follow symlinked dirs.
    queue: list[tuple[Path, int]] = [(search_root, 0)]
    while queue:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                if child.is_symlink():
                    continue
                if not child.is_dir():
                    continue
            except OSError:
                continue
            if _is_agent_scope_name(child.name):
                found.append(child)
            queue.append((child, depth + 1))
    return found


def _discover_agent_scopes(
    *,
    cgroup_root: Path | str | None = None,
    only_units: set[str] | frozenset[str] | None = None,
    proc_root: Path = Path("/proc"),
) -> list[_AgentScope]:
    """Locate ``sase-agent-*.scope`` directories under the user manager.

    With *cgroup_root* given, that tree is searched directly (tests pass a
    fake root). Otherwise the ``user@<uid>.service`` subtree is resolved
    from ``/proc/self/cgroup``, falling back to the conventional
    ``user.slice/user-<uid>.slice/user@<uid>.service`` path.

    At most 3 levels deep are searched. Returns nothing on non-Linux hosts
    or without unified cgroup v2. Under pytest an unfiltered scan of the
    real tree is refused: pass an explicit fake root or unit filter.
    """
    from sase.core.state_write_guard import pytest_context_detected

    if sys.platform != "linux":
        log.info("orphan scope discovery: not Linux; nothing eligible")
        return []
    if pytest_context_detected() and cgroup_root is None and only_units is None:
        raise RuntimeError(_REAPER_PYTEST_GUARD_MESSAGE)
    if not _cgroup_v2_unified(proc_root=proc_root):
        log.info("orphan scope discovery: no unified cgroup v2; nothing eligible")
        return []
    if cgroup_root is not None:
        search_root = Path(cgroup_root)
    else:
        cgroup_text = _own_cgroup_text(proc_root=proc_root)
        try:
            uid = os.getuid()
        except OSError:
            return []
        search_root = _user_manager_root(cgroup_text, uid=uid)
    wanted = set(only_units) if only_units is not None else None
    scopes: list[_AgentScope] = []
    for scope_dir in _iter_scope_dirs(
        search_root, max_depth=_REAPER_MAX_DISCOVERY_DEPTH
    ):
        if wanted is not None and scope_dir.name not in wanted:
            continue
        scopes.append(
            _AgentScope(
                unit=scope_dir.name,
                path=scope_dir,
                created_ns=_parse_scope_created_ns(scope_dir.name),
            )
        )
    scopes.sort(key=lambda scope: scope.unit)
    return scopes


def _read_agent_name(pid: int, *, proc_root: Path = Path("/proc")) -> str | None:
    """Best-effort ``SASE_AGENT_NAME`` read from ``/proc/<pid>/environ``."""
    try:
        data = (proc_root / str(pid) / "environ").read_bytes()
    except OSError:
        return None
    for entry in data.split(b"\0"):
        if entry.startswith(b"SASE_AGENT_NAME="):
            try:
                value = entry.split(b"=", 1)[1].decode("utf-8", errors="replace")
            except IndexError:
                return None
            value = value.strip()
            return value or None
    return None


def reap_orphaned_agent_scopes(
    *,
    apply: bool,
    min_age_seconds: float | None = None,
    cgroup_root: Path | str | None = None,
    only_units: set[str] | frozenset[str] | None = None,
    proc_root: Path = Path("/proc"),
    grace_seconds: float | None = None,
    spare_patterns: tuple[str, ...] | list[str] | None = None,
    now_ns: int | None = None,
    kill: Callable[[int, int], None] | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> _ReapResult:
    """Sweep ``sase-agent`` scopes whose runner is gone.

    Each discovered scope classifies as ``skipped_young`` (younger than
    *min_age_seconds*, or with an unparsable trailing timestamp, which fails
    closed), ``live`` (holds a runner or ``systemd-run`` member), ``empty``
    (no live members), ``spared_only`` (every member spared), or
    ``reapable``. Reapable scopes run :func:`_plan_scope_sweep` with no
    protect root and, when *apply* is true, :func:`_execute_scope_sweep`;
    with ``apply=False`` nothing is signalled.
    """
    if sys.platform != "linux":
        return _ReapResult(
            scanned=0,
            live=0,
            skipped_young=0,
            empty=0,
            spared_only=0,
            reaped=(),
            terminated=0,
            errors=0,
            reason="not_linux",
        )
    if not _cgroup_v2_unified(proc_root=proc_root):
        return _ReapResult(
            scanned=0,
            live=0,
            skipped_young=0,
            empty=0,
            spared_only=0,
            reaped=(),
            terminated=0,
            errors=0,
            reason="no_cgroup_v2",
        )
    if min_age_seconds is None:
        try:
            from sase.config._settings_system import (
                get_agent_scope_teardown_reaper_min_scope_age_seconds,
            )

            min_age_seconds = get_agent_scope_teardown_reaper_min_scope_age_seconds()
        except Exception:  # noqa: BLE001 - the reaper fails open to a safe default.
            min_age_seconds = 120
    if grace_seconds is None:
        try:
            from sase.config._settings_system import (
                get_agent_scope_teardown_term_grace_seconds,
            )

            grace_seconds = get_agent_scope_teardown_term_grace_seconds()
        except Exception:  # noqa: BLE001 - the reaper fails open to a safe default.
            grace_seconds = 3.0
    if spare_patterns is None:
        try:
            from sase.config._settings_system import (
                get_agent_scope_teardown_spare_process_patterns,
            )

            spare_patterns = tuple(get_agent_scope_teardown_spare_process_patterns())
        except Exception:  # noqa: BLE001 - the reaper fails open to a safe default.
            spare_patterns = tuple(DEFAULT_SPARE_PROCESS_PATTERNS)
    else:
        spare_patterns = tuple(spare_patterns)
    now = time.time_ns() if now_ns is None else int(now_ns)
    min_age = max(0.0, float(min_age_seconds))

    # The pytest guard lives in discovery; let its refusal propagate so a
    # test that forgets its fake root fails loudly instead of scanning host.
    scopes = _discover_agent_scopes(
        cgroup_root=cgroup_root, only_units=only_units, proc_root=proc_root
    )
    live = 0
    skipped_young = 0
    empty = 0
    spared_only = 0
    reaped: list[_ReapedScope] = []
    terminated_total = 0
    errors = 0
    for scope in scopes:
        try:
            if scope.created_ns is None:
                skipped_young += 1
                continue
            age_seconds = (now - scope.created_ns) / 1_000_000_000
            if age_seconds < min_age:
                skipped_young += 1
                continue
            members = _read_scope_members(scope.path, proc_root=proc_root)
            if not members:
                empty += 1
                continue
            if any(
                _is_agent_runner(member) or _is_systemd_run_member(member)
                for member in members
            ):
                live += 1
                continue
            plan = _plan_scope_sweep(
                members, protect_root=None, spare_patterns=spare_patterns
            )
            if not plan.targets:
                spared_only += 1
                continue
            agent_name = _read_agent_name(plan.targets[0].pid, proc_root=proc_root)
            entries = tuple(
                _format_entry(member) for member in plan.targets[:_REAPER_ENTRY_LIMIT]
            )
            terminated_here = 0
            if apply:
                sweep_kwargs: dict = {
                    "grace_seconds": float(grace_seconds),
                    "proc_root": proc_root,
                }
                if kill is not None:
                    sweep_kwargs["kill"] = kill
                if clock is not None:
                    sweep_kwargs["clock"] = clock
                if sleep is not None:
                    sweep_kwargs["sleep"] = sleep
                sweep_result = _execute_scope_sweep(plan, scope.path, **sweep_kwargs)
                terminated_here = len(sweep_result.terminated)
                terminated_total += terminated_here
            reaped.append(
                _ReapedScope(
                    unit=scope.unit,
                    agent_name=agent_name,
                    targets=len(plan.targets),
                    terminated=terminated_here,
                    entries=entries,
                )
            )
        except Exception:  # noqa: BLE001 - one bad scope never stops the pass.
            log.exception("Orphaned agent scope reap failed for %s", scope.unit)
            errors += 1
    return _ReapResult(
        scanned=len(scopes),
        live=live,
        skipped_young=skipped_young,
        empty=empty,
        spared_only=spared_only,
        reaped=tuple(reaped),
        terminated=terminated_total,
        errors=errors,
    )


__all__ = [
    "AGENT_SCOPE_UNIT_PREFIX",
    "DEFAULT_SPARE_PROCESS_PATTERNS",
    "RUNNER_SCRIPT_NAME",
    "reap_orphaned_agent_scopes",
    "sweep_own_agent_scope",
]
