"""Bounded teardown of a wedged provider process and the processes it leaked.

Once the host accepts an agent's final declaration the turn is over, so a
provider CLI that refuses to exit is terminated rather than waited on forever.
Providers routinely leak background processes from their tool sandbox, and a
leaked process can be the very thing keeping the provider alive, so the
provider's descendants are reaped along with it.

Two properties shape this module:

* **The descendant snapshot is taken before the provider is signalled.**
  Killing the provider first would reparent its children to ``init`` and
  break the ``ppid`` chain the walk relies on. Descendants are found through
  ``ppid``, never through the process group or session: a leaked shell that
  made itself a session leader is out of reach of ``killpg``.
* **Anything SASE deliberately detached is never signalled.** Monitors,
  agents, and procs are spawned with ``start_new_session=True`` precisely so
  they outlive the agent that started them, and until they reparent they are
  still reachable by a ``ppid`` walk. Registered live pids, the current
  process, and its ancestors are shielded, and the walk does not descend below
  a shielded pid.

Because the provider is already dead by the time the sweep signals anything,
the pid-reuse guard cannot be a ``ppid`` re-read (every orphan has already
reparented). Each target instead records a boot-aware process identity at
snapshot time and is signalled only while that identity still matches.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
import weakref
from collections import deque
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field

from sase.core.process_identity import process_identity_token

DEFAULT_TERMINATE_TIMEOUT_SECONDS = 10.0

_PS_TIMEOUT_SECONDS = 5.0
_SWEEP_TERM_GRACE_SECONDS = 2.0
_SWEEP_POLL_SECONDS = 0.1
_NOTE_ARGV_LIMIT = 3
_NOTE_ARGV_WIDTH = 160


@dataclass(frozen=True)
class _ProcessEntry:
    """One row of the process table."""

    pid: int
    ppid: int
    argv: str


@dataclass(frozen=True)
class _SweepTarget:
    """A descendant selected for reaping, pinned to one process identity."""

    pid: int
    ppid: int
    argv: str
    identity: str


@dataclass
class _DescendantSweepPlan:
    """The descendants to reap, or why none could be safely selected."""

    targets: list[_SweepTarget] = field(default_factory=list)
    skipped_reason: str | None = None


@dataclass
class TeardownStall:
    """Outcome of a watchdog-forced provider teardown.

    ``settled`` is set once the teardown has finished and the diagnostic
    artifact is written, so a stream loop that observed the provider exit can
    wait for the record to be complete before it reports the turn's result.
    """

    runtime: str
    provider_pid: int
    declared_at: str
    grace_seconds: float
    waited_seconds: float = 0.0
    descendants: list[dict[str, object]] = field(default_factory=list)
    sweep_skipped_reason: str | None = None
    settled: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def note(self) -> str:
        """One-line stderr diagnostic for this stall."""
        reaped = ""
        if self.descendants:
            shown = [
                _truncate(str(item.get("argv") or item.get("pid")))
                for item in self.descendants[:_NOTE_ARGV_LIMIT]
            ]
            extra = len(self.descendants) - len(shown)
            if extra > 0:
                shown.append(f"+{extra} more")
            reaped = (
                f" and reaped {len(self.descendants)} leaked process(es): "
                + "; ".join(shown)
            )
        elif self.sweep_skipped_reason:
            reaped = f" (descendant sweep skipped: {self.sweep_skipped_reason})"
        return (
            f"[sase] {self.runtime} (pid {self.provider_pid}) was still running "
            f"{round(self.waited_seconds, 1):g}s after its final declaration was accepted; "
            f"terminated it{reaped}. The completed reply is unaffected."
        )

    def to_json(self) -> dict[str, object]:
        """Serialize the artifact written as ``provider_teardown_stall.json``."""
        return {
            "runtime": self.runtime,
            "provider_pid": self.provider_pid,
            "declared_at": self.declared_at,
            "grace_seconds": self.grace_seconds,
            "waited_seconds": self.waited_seconds,
            "reaped_descendants": self.descendants,
            "sweep_skipped_reason": self.sweep_skipped_reason,
        }


_stalls: weakref.WeakKeyDictionary[subprocess.Popen[str], TeardownStall] = (
    weakref.WeakKeyDictionary()
)


def register_teardown_stall(
    process: subprocess.Popen[str], stall: TeardownStall
) -> None:
    """Record that the watchdog is tearing *process* down."""
    _stalls[process] = stall


def teardown_stall_for(process: subprocess.Popen[str]) -> TeardownStall | None:
    """Return the stall record when the watchdog tore *process* down."""
    return _stalls.get(process)


def _parse_process_table(text: str) -> list[_ProcessEntry]:
    """Parse ``ps -o pid=,ppid=,args=`` output, skipping malformed rows."""
    entries: list[_ProcessEntry] = []
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        entries.append(_ProcessEntry(pid, ppid, parts[2] if len(parts) > 2 else ""))
    return entries


def _read_process_table() -> list[_ProcessEntry]:
    """Snapshot the whole process table, or ``[]`` when ``ps`` is unusable.

    The repo has no ``psutil`` dependency, so the pid -> ppid map comes from
    ``ps``. ``-ww`` keeps long argv from being truncated.
    """
    try:
        result = subprocess.run(
            ["ps", "-axww", "-o", "pid=,ppid=,args="],
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return _parse_process_table(result.stdout)


def _ancestor_pids(pid: int, parents: Mapping[int, int]) -> set[int]:
    """Return *pid* and every ancestor reachable through *parents*."""
    chain: set[int] = set()
    current = pid
    while current > 0 and current not in chain:
        chain.add(current)
        current = parents.get(current, 0)
    return chain


def _select_reapable_descendants(
    root_pid: int,
    table: list[_ProcessEntry],
    *,
    protected_pids: Collection[int],
    current_pid: int | None = None,
) -> list[_ProcessEntry]:
    """Walk *table* transitively from *root_pid*, honouring the exclusions.

    Protected pids, the current process, and its ancestors are neither
    selected nor descended into: whatever a detached monitor or agent spawned
    belongs to it, not to the provider that happened to start it. A ``ppid``
    walk is deliberate, so a descendant in another session (a leaked shell
    that made itself a session leader) is still found.
    """
    children: dict[int, list[_ProcessEntry]] = {}
    parents: dict[int, int] = {}
    for entry in table:
        children.setdefault(entry.ppid, []).append(entry)
        parents[entry.pid] = entry.ppid

    own_pid = os.getpid() if current_pid is None else current_pid
    shielded = _ancestor_pids(own_pid, parents) | set(protected_pids)
    selected: list[_ProcessEntry] = []
    seen = {root_pid}
    queue = deque(children.get(root_pid, []))
    while queue:
        entry = queue.popleft()
        if entry.pid in seen:
            continue
        seen.add(entry.pid)
        if entry.pid in shielded:
            continue
        selected.append(entry)
        queue.extend(children.get(entry.pid, []))
    return selected


def _registered_live_pids() -> frozenset[int] | None:
    """Return the pids SASE itself tracks as live, or ``None`` if unreadable.

    Agents and monitors come from the same listing ``sase agent list`` reads
    (monitor members are agent-family rows); procs come from the durable proc
    store. Imports are deferred because this only runs when a stall fires.
    """
    try:
        from sase.agent.running_listing import list_running_agents
        from sase.procs.models import ACTIVE_PROC_STATUSES
        from sase.procs.store import read_procs

        agents = list_running_agents(index_freshness="revalidate")
        procs = read_procs(status=ACTIVE_PROC_STATUSES)
    except Exception:
        return None
    pids = {agent.pid for agent in agents}
    pids.update(proc.pid for proc in procs)
    return frozenset(pid for pid in pids if pid is not None)


def _plan_descendant_sweep(
    root_pid: int,
    *,
    read_table: Callable[[], list[_ProcessEntry]] | None = None,
    read_registry: Callable[[], frozenset[int] | None] | None = None,
) -> _DescendantSweepPlan:
    """Select the descendants of *root_pid* that are safe to reap.

    An unreadable registry means SASE cannot tell a leaked process from a
    detached monitor, so nothing is selected: an unreaped leak is a smaller
    harm than a killed monitor.
    """
    table = (read_table or _read_process_table)()
    if not table:
        return _DescendantSweepPlan(skipped_reason="process table unavailable")
    protected = (read_registry or _registered_live_pids)()
    if protected is None:
        return _DescendantSweepPlan(skipped_reason="live agent registry unavailable")

    targets: list[_SweepTarget] = []
    for entry in _select_reapable_descendants(
        root_pid, table, protected_pids=protected
    ):
        identity = process_identity_token(entry.pid)
        # Without identity evidence a later signal could hit a recycled pid.
        if identity:
            targets.append(_SweepTarget(entry.pid, entry.ppid, entry.argv, identity))
    return _DescendantSweepPlan(targets=targets)


def terminate_process_tree(
    process: subprocess.Popen[str],
    stall: TeardownStall,
    *,
    timeout: float = DEFAULT_TERMINATE_TIMEOUT_SECONDS,
    plan_sweep: Callable[[int], _DescendantSweepPlan] | None = None,
) -> None:
    """Terminate *process*, then reap the descendants it leaked.

    The descendants that were still alive and got signalled are recorded on
    *stall*, along with why the sweep was skipped when it could not run. Never
    waits longer than a small multiple of *timeout*, even when a process
    ignores SIGKILL.
    """
    plan = (plan_sweep or _plan_descendant_sweep)(process.pid)
    _stop_process(process, timeout)
    stall.descendants = [
        {"pid": target.pid, "ppid": target.ppid, "argv": target.argv}
        for target in _sweep(plan.targets)
    ]
    stall.sweep_skipped_reason = plan.skipped_reason


def _stop_process(process: subprocess.Popen[str], timeout: float) -> None:
    """SIGTERM *process*, escalating to SIGKILL, without waiting forever."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        pass
    process.kill()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass


def _sweep(targets: list[_SweepTarget]) -> list[_SweepTarget]:
    """SIGTERM then SIGKILL *targets*; return those that were alive."""
    signalled = _signal_alive(targets, signal.SIGTERM)
    deadline = time.monotonic() + _SWEEP_TERM_GRACE_SECONDS
    survivors = signalled
    while survivors and time.monotonic() < deadline:
        time.sleep(_SWEEP_POLL_SECONDS)
        survivors = [target for target in survivors if _is_same_process(target)]
    _signal_alive(survivors, signal.SIGKILL)
    return signalled


def _signal_alive(
    targets: list[_SweepTarget], sig: signal.Signals
) -> list[_SweepTarget]:
    """Send *sig* to each target that still has its snapshot identity."""
    signalled: list[_SweepTarget] = []
    for target in targets:
        if not _is_same_process(target):
            continue
        try:
            os.kill(target.pid, sig)
        except OSError:
            continue
        signalled.append(target)
    return signalled


def _is_same_process(target: _SweepTarget) -> bool:
    """Whether ``target.pid`` still names the process that was snapshotted."""
    return process_identity_token(target.pid) == target.identity


def _truncate(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= _NOTE_ARGV_WIDTH:
        return one_line
    return one_line[: _NOTE_ARGV_WIDTH - 3] + "..."


__all__ = [
    "DEFAULT_TERMINATE_TIMEOUT_SECONDS",
    "TeardownStall",
    "register_teardown_stall",
    "teardown_stall_for",
    "terminate_process_tree",
]
