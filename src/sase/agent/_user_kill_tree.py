"""Verified termination of an agent's whole process set."""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from sase.agent._user_kill_intent import (
    has_user_kill_intent,
    read_recorded_scratch_key,
    record_user_kill_result,
    target_identity_is_verified,
    user_kill_intent_path,
)
from sase.agent._user_kill_types import (
    DEFAULT_TERMINATE_GRACE_SECONDS,
    POLL_INTERVAL_SECONDS,
    AgentTerminationResult,
    Kill,
    Killpg,
    RegistryFn,
    SleepFn,
    TimeFn,
)
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
    discover_strong_members,
    discover_weak_members,
    proc_available,
    process_is_running,
    read_process_row,
    read_process_table,
    shielded_pids,
)
from sase.core.process_identity import process_identity_token

_POST_KILL_WAIT_SECONDS = 2.0


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
        if target_identity_is_verified(self.pid, artifacts_dir=artifacts_dir):
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
        return str(user_kill_intent_path(artifacts_dir))
    return None


def terminate_agent_processes(
    pid: int,
    *,
    artifacts_dir: str | Path | None = None,
    grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS,
    post_kill_seconds: float = _POST_KILL_WAIT_SECONDS,
    poll_interval: float = POLL_INTERVAL_SECONDS,
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
        scratch_key=scratch_key or read_recorded_scratch_key(artifacts_dir),
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
    record_user_kill_result(marker_str, result)
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


__all__ = [
    "terminate_agent_processes",
]
