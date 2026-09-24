"""Shared helpers for explicit user-requested agent termination.

Termination has two stages. The *immediate* stage
(:func:`request_user_kill` with ``wait=False``) records the user's intent and
sends one SIGTERM; it is cheap enough for an interactive caller. The *durable*
stage (:func:`terminate_agent_processes`) finds the agent's whole process set,
escalates to SIGKILL, and verifies death; it must run somewhere that survives
the caller, such as the ``sase agent persist-cleanup`` proc.
"""

from __future__ import annotations

import json
import os
import signal
import threading
import time
import uuid
from collections.abc import Callable, Collection
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sase.agent.process_registry import (
    ProcessRegistry,
    RegisteredSupervisor,
    read_process_registry,
)
from sase.agent.process_tree import (
    REASON_DESCENDANT,
    REASON_GROUP,
    REASON_RUNNER,
    ProcessRow,
    descendants_of,
    discover_strong_members,
    discover_weak_members,
    proc_available,
    process_is_running,
    read_process_row,
    read_process_table,
    shielded_pids,
)
from sase.core.process_identity import (
    pid_is_thread,
    process_identity_matches,
    process_identity_token,
)

USER_KILL_INTENT_MARKER = ".sase_user_kill_pending"

# The ``sase tool run`` wrapper escalates its own child from SIGTERM to SIGKILL
# after ``sase.tool.executor_process.TERM_ESCALATE_SECONDS`` (5s). The default
# grace must outlast that so wrappers can clean up their children before the
# tree is SIGKILLed; a test pins the relationship.
DEFAULT_TERMINATE_GRACE_SECONDS = 6.0

_IMMEDIATE_ESCALATION_GRACE_SECONDS = 0.5
_POST_KILL_WAIT_SECONDS = 2.0
_POLL_INTERVAL_SECONDS = 0.05
_SCRATCH_KEY_META_FIELD = "launch_scratch_key"

Killpg = Callable[[int, int], None]
Kill = Callable[[int, int], None]
SleepFn = Callable[[float], None]
TimeFn = Callable[[], float]
RegistryFn = Callable[[int], ProcessRegistry | None]


@dataclass(frozen=True)
class AgentTerminationResult:
    """Outcome of a user-requested agent termination attempt.

    ``survivors`` lists the pids that were still running when termination gave
    up; it is empty whenever ``success`` is true.
    """

    success: bool
    status: str
    pid: int
    pgid: int
    marker_path: str | None = None
    escalated: bool = False
    error: str | None = None
    survivors: tuple[int, ...] = ()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _user_kill_intent_path(artifacts_dir: str | Path) -> Path:
    return Path(artifacts_dir) / USER_KILL_INTENT_MARKER


def _write_user_kill_intent(
    artifacts_dir: str | Path | None,
    *,
    pid: int,
    source: str,
    reason: str | None = None,
    timestamp: float | None = None,
) -> Path | None:
    """Persist explicit user-kill intent before signalling an agent."""
    if artifacts_dir is None:
        return None
    marker_path = _user_kill_intent_path(artifacts_dir)
    marker_data: dict[str, Any] = {
        "schema_version": 1,
        "timestamp": time.time() if timestamp is None else timestamp,
        "pid": pid,
        "source": source,
    }
    if reason:
        marker_data["reason"] = reason
    try:
        _atomic_write_json(marker_path, marker_data)
    except OSError:
        return None
    return marker_path


def _read_user_kill_intent(artifacts_dir: str | Path) -> dict[str, Any] | None:
    """Read the durable user-kill intent marker without deleting it."""
    try:
        with open(_user_kill_intent_path(artifacts_dir), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def has_user_kill_intent(artifacts_dir: str | Path) -> bool:
    return _read_user_kill_intent(artifacts_dir) is not None


def ensure_user_kill_intent(
    artifacts_dir: str | Path | None,
    *,
    pid: int,
    source: str,
    reason: str | None = None,
) -> Path | None:
    """Return the intent marker path, writing one only when none exists yet.

    The durable stage usually finds the marker the interactive stage wrote and
    must not overwrite its timestamp or source; a dismissal safety net finds
    none and records the user's intent itself so the runner classifies the
    signal as a user kill.
    """
    if artifacts_dir is None:
        return None
    if has_user_kill_intent(artifacts_dir):
        return _user_kill_intent_path(artifacts_dir)
    return _write_user_kill_intent(artifacts_dir, pid=pid, source=source, reason=reason)


def _record_user_kill_result(
    marker_path: str | Path | None, result: AgentTerminationResult
) -> None:
    if marker_path is None:
        return
    path = Path(marker_path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["result"] = asdict(result)
    data["result_timestamp"] = time.time()
    try:
        _atomic_write_json(path, data)
    except OSError:
        pass


def _read_agent_meta_field(artifacts_dir: str | Path | None, field: str) -> object:
    if artifacts_dir is None:
        return None
    for marker_name in ("agent_meta.json", "running.json"):
        try:
            with open(Path(artifacts_dir) / marker_name, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and field in data:
            return data.get(field)
    return None


def _read_recorded_process_identity(
    artifacts_dir: str | Path | None,
) -> object | None:
    return _read_agent_meta_field(artifacts_dir, "process_identity")


def _read_recorded_scratch_key(artifacts_dir: str | Path | None) -> str | None:
    value = _read_agent_meta_field(artifacts_dir, _SCRATCH_KEY_META_FIELD)
    return value if isinstance(value, str) and value else None


def _target_identity_is_verified(
    pid: int,
    *,
    artifacts_dir: str | Path | None,
) -> bool:
    if pid_is_thread(pid):
        return False
    return process_identity_matches(pid, _read_recorded_process_identity(artifacts_dir))


def live_verified_agent_pid(pid: int, *, artifacts_dir: str | Path | None) -> bool:
    """Whether *pid* is running and provably the process the agent recorded.

    Stricter than the identity check a user-requested kill applies: evidence
    that is missing or unreadable counts as *not* verified, because callers use
    this to decide whether to signal a pid nobody explicitly asked to kill.
    """
    recorded = _read_recorded_process_identity(artifacts_dir)
    if not isinstance(recorded, str) or ":" not in recorded:
        return False
    if pid_is_thread(pid) or not process_is_running(pid):
        return False
    return process_identity_token(pid) == recorded


@dataclass(frozen=True)
class _Target:
    """One process selected for termination, pinned to its identity."""

    pid: int
    identity: str
    reason: str


class _TreeTermination:
    """State for one verified termination of an agent's process set."""

    def __init__(
        self,
        pid: int,
        *,
        artifacts_dir: str | Path | None,
        scratch_key: str | None,
        protected_pids: Collection[int],
        killpg: Killpg,
        kill: Kill,
        sleep_fn: SleepFn,
        monotonic_fn: TimeFn,
        poll_interval: float,
        registry_fn: RegistryFn,
    ) -> None:
        self.pid = pid
        self.scratch_key = scratch_key
        self.protected_pids = frozenset(protected_pids)
        self._killpg = killpg
        self._kill = kill
        self._sleep = sleep_fn
        self._monotonic = monotonic_fn
        self._poll = max(poll_interval, 0.0)
        self._registry_fn = registry_fn
        self._registry: ProcessRegistry | None = None
        self._registry_read = False
        self.targets: dict[int, _Target] = {}
        self.denied: set[int] = set()
        self.supervisors: dict[int, RegisteredSupervisor] = {}
        self._stopped_supervisors: set[str] = set()
        self._group_shielded = False
        self.root_state = self._classify_root(artifacts_dir)

    def _classify_root(self, artifacts_dir: str | Path | None) -> str:
        """``live``, ``gone`` (no such process), or ``recycled`` (pid reused)."""
        if not process_is_running(self.pid):
            return "gone"
        if _target_identity_is_verified(self.pid, artifacts_dir=artifacts_dir):
            return "live"
        return "recycled"

    @property
    def _trust_root_pid(self) -> bool:
        return self.root_state != "recycled"

    def _read_registry(self) -> ProcessRegistry | None:
        if not self._registry_read:
            self._registry_read = True
            try:
                self._registry = self._registry_fn(self.pid)
            except Exception:
                self._registry = None
        return self._registry

    def _pin(self, pid: int, reason: str) -> _Target | None:
        identity = process_identity_token(pid)
        if not identity and proc_available():
            return None  # already gone
        return _Target(pid, identity, reason)

    def discover(self) -> list[_Target]:
        """Find processes that belong to the agent, pinning each new one."""
        table = read_process_table()
        if not table:
            found = {self.pid: REASON_RUNNER} if self.root_state == "live" else {}
            discovered = found
        else:
            shielded = shielded_pids(table, extra=self.protected_pids)
            self._group_shielded = any(
                row.pgid == self.pid for pid, row in table.items() if pid in shielded
            )
            discovered = dict(
                discover_strong_members(
                    self.pid,
                    table,
                    scratch_key=self.scratch_key,
                    trust_root_pid=self._trust_root_pid,
                    shielded=shielded,
                )
            )
            discovered.update(self._weak_members(table, discovered, shielded))
        new_targets: list[_Target] = []
        for pid, reason in discovered.items():
            if pid in self.targets:
                continue
            target = self._pin(pid, reason)
            if target is not None:
                self.targets[pid] = target
                new_targets.append(target)
        self._bind_supervisors(new_targets, table)
        return new_targets

    def _weak_members(
        self,
        table: dict[int, ProcessRow],
        strong: dict[int, str],
        shielded: frozenset[int],
    ) -> dict[int, str]:
        candidates = discover_weak_members(
            self.pid,
            strong,
            table,
            trust_root_pid=self._trust_root_pid,
            protected=shielded,
        )
        if not candidates:
            return {}
        registry = self._read_registry()
        if registry is None:
            # Without the registry a leaked descendant cannot be told apart
            # from a sibling agent that is still parented to its launcher.
            return {}
        return dict.fromkeys(
            discover_weak_members(
                self.pid,
                strong,
                table,
                trust_root_pid=self._trust_root_pid,
                protected=shielded | registry.protected_pids,
            ),
            REASON_DESCENDANT,
        )

    def _bind_supervisors(
        self, new_targets: list[_Target], table: dict[int, ProcessRow]
    ) -> None:
        """Route escaped registered supervisors to their canonical stop."""
        escaped = [
            target
            for target in new_targets
            if target.reason not in {REASON_RUNNER, REASON_GROUP}
        ]
        if not escaped:
            return
        registry = self._read_registry()
        if registry is None:
            return
        for target in escaped:
            row = table.get(target.pid)
            owned_ids = {target.pid}
            if row is not None:
                owned_ids.add(row.pgid)
            for supervisor in registry.supervisors:
                if owned_ids & supervisor.pids:
                    self.supervisors[target.pid] = supervisor
                    break

    def alive(self, target: _Target) -> bool:
        row = read_process_row(target.pid)
        if row is None:
            return not proc_available() and _pid_exists(target.pid)
        if row.is_dead:
            return False
        return not target.identity or process_identity_token(target.pid) == (
            target.identity
        )

    def alive_targets(self) -> list[_Target]:
        return [target for target in self.targets.values() if self.alive(target)]

    def _group_signalable(self) -> bool:
        if not self._trust_root_pid or self._group_shielded:
            return False
        if self.root_state == "live":
            try:
                if os.getpgid(self.pid) != self.pid:
                    return False
            except OSError:
                return False
        try:
            return os.getpgid(0) != self.pid
        except OSError:
            return False

    def signal_group(self, sig: int) -> None:
        if not self._group_signalable():
            return
        try:
            self._killpg(self.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def signal(self, target: _Target, sig: int) -> bool:
        """Signal *target* only while it is still the pinned process."""
        if not self.alive(target):
            return False
        try:
            self._kill(target.pid, sig)
        except ProcessLookupError:
            return False
        except PermissionError:
            self.denied.add(target.pid)
            return False
        return True

    def stop_supervisors(self) -> None:
        """Stop each bound supervisor once, through its canonical stop."""
        for supervisor in list(self.supervisors.values()):
            if supervisor.label in self._stopped_supervisors:
                continue
            self._stopped_supervisors.add(supervisor.label)
            try:
                supervisor.stop()
            except Exception:
                # The canonical stop failed; treat the members as plain
                # processes so they are still signalled and verified.
                for member_pid in [
                    member
                    for member, bound in self.supervisors.items()
                    if bound is supervisor
                ]:
                    del self.supervisors[member_pid]
                    self.signal(self.targets[member_pid], signal.SIGTERM)

    def wait_for_exit(self, seconds: float) -> None:
        deadline = self._monotonic() + max(seconds, 0.0)
        while self.alive_targets():
            if self._monotonic() >= deadline:
                return
            self._sleep(self._poll)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _default_marker_path(
    artifacts_dir: str | Path | None, marker_path: str | Path | None
) -> str | None:
    if marker_path is not None:
        return str(marker_path)
    if artifacts_dir is not None and has_user_kill_intent(artifacts_dir):
        return str(_user_kill_intent_path(artifacts_dir))
    return None


def terminate_agent_processes(
    pid: int,
    *,
    artifacts_dir: str | Path | None = None,
    grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS,
    post_kill_seconds: float = _POST_KILL_WAIT_SECONDS,
    poll_interval: float = _POLL_INTERVAL_SECONDS,
    marker_path: str | Path | None = None,
    scratch_key: str | None = None,
    protected_pids: Collection[int] = (),
    killpg: Killpg = os.killpg,
    kill: Kill = os.kill,
    sleep_fn: SleepFn = time.sleep,
    monotonic_fn: TimeFn = time.monotonic,
    registry_fn: RegistryFn | None = None,
) -> AgentTerminationResult:
    """Terminate an agent's whole process set and verify that it is dead.

    The set is the runner plus every process in its group, in its session,
    carrying its launch scratch key, or below it in the ``ppid`` tree. Each
    process is pinned to its boot-aware identity and only signalled while that
    identity still matches; this process and its ancestors are never signalled.
    Registered SASE supervisors found in the set are stopped through their
    canonical stop so store records settle.

    Sequence: SIGTERM to the group and every pinned pid, wait up to
    *grace_seconds*, rediscover (catching late children), SIGKILL whatever is
    left, wait up to *post_kill_seconds*, and report anything still running as
    ``survivors``. The result is recorded in the intent marker when there is
    one. A runner pid that is not a group leader is signalled directly with its
    tree; it is never reported ``already_stopped`` because ``killpg`` found no
    such group.
    """
    marker_str = _default_marker_path(artifacts_dir, marker_path)
    termination = _TreeTermination(
        pid,
        artifacts_dir=artifacts_dir,
        scratch_key=scratch_key or _read_recorded_scratch_key(artifacts_dir),
        protected_pids=protected_pids,
        killpg=killpg,
        kill=kill,
        sleep_fn=sleep_fn,
        monotonic_fn=monotonic_fn,
        poll_interval=poll_interval,
        registry_fn=registry_fn or read_process_registry,
    )
    termination.discover()
    result = _run_termination(
        termination,
        marker_str,
        grace_seconds=grace_seconds,
        post_kill_seconds=post_kill_seconds,
    )
    _record_user_kill_result(marker_str, result)
    return result


def _run_termination(
    termination: _TreeTermination,
    marker_str: str | None,
    *,
    grace_seconds: float,
    post_kill_seconds: float,
) -> AgentTerminationResult:
    pid = termination.pid
    if not termination.targets:
        status = (
            "identity_mismatch"
            if termination.root_state == "recycled"
            else ("already_stopped")
        )
        return AgentTerminationResult(True, status, pid, pid, marker_path=marker_str)

    termination.signal_group(signal.SIGTERM)
    plain = [
        target
        for target in termination.targets.values()
        if target.pid not in termination.supervisors
    ]
    for target in plain:
        termination.signal(target, signal.SIGTERM)
    termination.stop_supervisors()
    termination.wait_for_exit(grace_seconds)

    # Rediscovery catches children that appeared while the tree shut down.
    termination.discover()
    escalated = False
    stragglers = termination.alive_targets()
    if stragglers:
        termination.signal_group(signal.SIGKILL)
        for target in stragglers:
            escalated = termination.signal(target, signal.SIGKILL) or escalated
        termination.wait_for_exit(post_kill_seconds)

    survivors = tuple(sorted(target.pid for target in termination.alive_targets()))
    if survivors:
        denied_only = all(survivor in termination.denied for survivor in survivors)
        return AgentTerminationResult(
            False,
            "permission_denied" if denied_only else "survivors",
            pid,
            pid,
            marker_path=marker_str,
            escalated=escalated,
            error=(
                f"process(es) still running after SIGKILL: "
                f"{', '.join(str(survivor) for survivor in survivors)}"
            ),
            survivors=survivors,
        )
    return AgentTerminationResult(
        True,
        "force_killed" if escalated else "killed",
        pid,
        pid,
        marker_path=marker_str,
        escalated=escalated,
    )


def _signal_immediately(
    pid: int,
    *,
    artifacts_dir: str | Path | None,
    marker_path: str | None,
    killpg: Killpg,
) -> AgentTerminationResult:
    """Send the interactive stage's single SIGTERM to the agent's group."""
    pgid = pid
    if not _target_identity_is_verified(pid, artifacts_dir=artifacts_dir):
        result = AgentTerminationResult(
            True, "identity_mismatch", pid, pgid, marker_path=marker_path
        )
        _record_user_kill_result(marker_path, result)
        return result
    try:
        killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        result = _signal_non_leader(pid, marker_path=marker_path)
        if result.status != "killed":
            _record_user_kill_result(marker_path, result)
            return result
    except PermissionError as exc:
        result = AgentTerminationResult(
            False,
            "permission_denied",
            pid,
            pgid,
            marker_path=marker_path,
            error=str(exc) or "permission denied",
        )
        _record_user_kill_result(marker_path, result)
        return result

    initial = AgentTerminationResult(True, "killed", pid, pgid, marker_path=marker_path)
    _record_user_kill_result(marker_path, initial)
    return initial


def _signal_non_leader(pid: int, *, marker_path: str | None) -> AgentTerminationResult:
    """SIGTERM a pid that has no process group of its own, plus its tree.

    ``killpg`` on such a pid raises ``ProcessLookupError`` even though the
    process is alive, so the pid is re-checked before the group failure is
    believed.
    """
    if not process_is_running(pid):
        return AgentTerminationResult(
            True, "already_stopped", pid, pid, marker_path=marker_path
        )
    tree = [pid, *descendants_of([pid], read_process_table())]
    for target in tree:
        try:
            os.kill(target, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            if target == pid:
                return AgentTerminationResult(
                    False,
                    "permission_denied",
                    pid,
                    pid,
                    marker_path=marker_path,
                    error=str(exc) or "permission denied",
                )
    return AgentTerminationResult(True, "killed", pid, pid, marker_path=marker_path)


def escalate_user_kill_in_background(
    pid: int,
    *,
    artifacts_dir: str | Path | None,
    marker_path: str | Path | None = None,
    grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS,
) -> threading.Thread:
    """Run :func:`terminate_agent_processes` on a daemon thread.

    The thread dies with its process, so it is only a fallback for callers that
    could not hand termination to a durable proc.
    """
    thread = threading.Thread(
        target=terminate_agent_processes,
        args=(pid,),
        kwargs={
            "artifacts_dir": artifacts_dir,
            "grace_seconds": grace_seconds,
            "marker_path": marker_path,
        },
        name=f"sase-user-kill-{pid}",
        daemon=True,
    )
    thread.start()
    return thread


def request_user_kill(
    pid: int,
    *,
    artifacts_dir: str | Path | None,
    source: str,
    reason: str | None = None,
    wait: bool = True,
    background: bool = False,
    grace_seconds: float | None = None,
    poll_interval: float = _POLL_INTERVAL_SECONDS,
    killpg: Killpg = os.killpg,
    sleep_fn: SleepFn = time.sleep,
    monotonic_fn: TimeFn = time.monotonic,
) -> AgentTerminationResult:
    """Write user-kill intent, then terminate the agent.

    With ``wait=True`` this runs the full verified termination and blocks
    until the process set is dead or *grace_seconds* plus the post-kill window
    have elapsed. With ``wait=False`` it only sends the immediate SIGTERM; add
    ``background=True`` to also escalate on a daemon thread. Neither
    ``wait=False`` form verifies anything, so callers must hand the rest to a
    durable stage.
    """
    marker_path = _write_user_kill_intent(
        artifacts_dir,
        pid=pid,
        source=source,
        reason=reason,
    )
    if wait:
        return terminate_agent_processes(
            pid,
            artifacts_dir=artifacts_dir,
            grace_seconds=(
                DEFAULT_TERMINATE_GRACE_SECONDS
                if grace_seconds is None
                else grace_seconds
            ),
            poll_interval=poll_interval,
            marker_path=marker_path,
            killpg=killpg,
            sleep_fn=sleep_fn,
            monotonic_fn=monotonic_fn,
        )
    result = _signal_immediately(
        pid,
        artifacts_dir=artifacts_dir,
        marker_path=str(marker_path) if marker_path is not None else None,
        killpg=killpg,
    )
    if background and result.success and result.status == "killed":
        escalate_user_kill_in_background(
            pid,
            artifacts_dir=artifacts_dir,
            marker_path=marker_path,
            grace_seconds=(
                _IMMEDIATE_ESCALATION_GRACE_SECONDS
                if grace_seconds is None
                else grace_seconds
            ),
        )
    return result


__all__ = [
    "DEFAULT_TERMINATE_GRACE_SECONDS",
    "USER_KILL_INTENT_MARKER",
    "AgentTerminationResult",
    "ensure_user_kill_intent",
    "escalate_user_kill_in_background",
    "has_user_kill_intent",
    "live_verified_agent_pid",
    "request_user_kill",
    "terminate_agent_processes",
]
