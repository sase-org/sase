"""The lease itself: a crash-safe hold on several host-global worker tokens.

Split out of :mod:`tests._suite_gate`, which keeps the pytest-facing entry
points. This module owns the state machine — request, grant, heartbeat,
release — and the process-wide registry that lets
:func:`tests._suite_gate.record_lease_progress` find the lease a heartbeat
belongs to.
"""

from __future__ import annotations

from collections.abc import Callable
import fcntl
import os
import sys
import threading
import time
from pathlib import Path
from typing import IO

import pytest

from sase.core.process_identity import process_identity_token
from tests._suite_gate_budget import fit_request_to_budget
from tests._suite_gate_env import (
    DISABLED_ENV,
    FDS_ENV,
    GOVERNED_ENV,
    LEASE_ENV_NAMES,
    LEASE_ID_ENV,
    LEASE_PID_ENV,
    holder_max_hold,
    holder_stale_timeout,
    holder_watchdog_interval,
)
from tests._suite_gate_holders import (
    reclaim_message,
    reclaim_reason_from_state,
    reclaim_wedged_holders,
    write_holder_metadata,
)
from tests._suite_gate_messages import timeout_message, waiting_message
from tests._suite_gate_pool import (
    POOL_FILE_NAME,
    read_pool_capacity,
    refresh_token_heartbeats,
    release_token_files,
    scan_active_holders,
    try_acquire_tokens,
    write_pool_capacity,
)
from tests._suite_gate_progress import read_progress_sidecar, remove_progress_sidecar
from tests._suite_gate_waiters import (
    bounded_grant_limit,
    find_waiter,
    read_waiter_state,
    remove_dead_waiters,
    write_waiter_state,
)


_POLL_INTERVAL_SECONDS = 2.0
_STATUS_INTERVAL_SECONDS = 30.0


class WorkerTokenTimeout(pytest.UsageError):
    """A lease acquire that waited past its deadline without tokens.

    A subclass of ``pytest.UsageError`` so existing ``except
    pytest.UsageError`` callers keep working; only the token-wait
    refusal recorder catches this subclass specifically.
    """


#: Every lease this process holds, keyed by lease id, so a progress event can
#: reach the lease whose tokens it should refresh.
_leases_by_id: dict[str, WorkerTokenLease] = {}


class WorkerTokenLease:
    """A crash-safe lease over several host-global pytest worker tokens."""

    def __init__(
        self,
        directory: Path,
        budget: int,
        timeout: float,
        *,
        capacity_is_explicit: bool = False,
        poll_interval: float = _POLL_INTERVAL_SECONDS,
        status_interval: float = _STATUS_INTERVAL_SECONDS,
        stale_timeout: float | None = None,
        max_hold: float | None = None,
        watchdog_interval: float | None = None,
        now: Callable[[], float] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if budget < 1:
            raise ValueError("budget must be positive")
        self._directory = directory
        self._budget = budget
        self._timeout = timeout
        self._capacity_is_explicit = capacity_is_explicit
        self._poll_interval = poll_interval
        self._status_interval = status_interval
        self._stale_timeout = stale_timeout
        self._max_hold = max_hold
        self._watchdog_interval = watchdog_interval
        self._now = now or time.time
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._token_files: list[IO[str]] = []
        self._previous_environment: dict[str, str | None] = {}
        self._effective_budget: int | None = None
        self._lease_id: str | None = None
        self._started: float | None = None
        self._lock = threading.Lock()
        self._watchdog_stop = threading.Event()
        self._watchdog_started = False
        self._signaled_leases: dict[str, int] = {}
        self._waiter_ticket: int | None = None

    @property
    def granted(self) -> int:
        """Return the number of tokens currently held by this lease."""
        return len(self._token_files)

    @property
    def file_descriptors(self) -> tuple[int, ...]:
        """Return the leased descriptors, primarily for exec-boundary checks."""
        return tuple(token_file.fileno() for token_file in self._token_files)

    def acquire(self, floor: int, ceiling: int, *, exact: bool = False) -> int:
        """Atomically reach ``floor``, then greedily grow through ``ceiling``."""
        self._prepare_request(floor, ceiling)
        deadline = self._monotonic() + self._timeout
        next_status = self._monotonic() + self._status_interval

        try:
            while True:
                granted, last_available, last_holders = self._attempt(
                    floor, ceiling, exact=exact, queue_waiter=True
                )
                if granted:
                    return granted

                now = self._monotonic()
                if now >= next_status:
                    print(
                        waiting_message(
                            floor,
                            ceiling,
                            last_available,
                            last_holders,
                            stale=self._effective_stale_timeout(),
                            max_hold=self._effective_max_hold(),
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                    next_status = now + self._status_interval

                if now >= deadline:
                    raise WorkerTokenTimeout(
                        timeout_message(
                            self._timeout,
                            floor,
                            ceiling,
                            last_available,
                            last_holders,
                            stale=self._effective_stale_timeout(),
                            max_hold=self._effective_max_hold(),
                        )
                    )

                self._sleep(min(self._poll_interval, max(0.0, deadline - now)))
        except BaseException:
            self._cancel_waiter_ticket()
            raise

    def try_acquire(self, floor: int, ceiling: int) -> int:
        """Ask once for ``floor``..``ceiling`` tokens; return ``0`` if refused.

        The same atomic attempt :meth:`acquire` loops over, made exactly once.
        A caller that must never queue behind another agent's run — the
        diff-scoped lane's middle gear, whose whole promise is that it does not
        wait — asks with this instead and takes no for an answer.
        """
        self._prepare_request(floor, ceiling)
        granted, _available, _holders = self._attempt(
            floor, ceiling, exact=False, queue_waiter=False
        )
        return granted

    def _prepare_request(self, floor: int, ceiling: int) -> None:
        if self._token_files:
            raise RuntimeError("worker-token lease is already acquired")
        if floor < 1 or ceiling < floor:
            raise ValueError("token floor and ceiling must be positive and ordered")
        self._directory.mkdir(parents=True, exist_ok=True)

    def _attempt(
        self, floor: int, ceiling: int, *, exact: bool, queue_waiter: bool
    ) -> tuple[int, int, dict[Path, str]]:
        """One pool-locked grant attempt: ``(granted, available, holders)``.

        ``granted`` is zero when the pool could not cover ``floor``; the
        remaining two describe what was in the way, which is what
        :meth:`acquire` prints while it waits.
        """
        pool_file = (self._directory / POOL_FILE_NAME).open("a+", encoding="utf-8")
        try:
            fcntl.flock(pool_file.fileno(), fcntl.LOCK_EX)
            waiter_state = read_waiter_state(self._directory)
            waiters, removed_dead_waiters = remove_dead_waiters(waiter_state["waiters"])
            waiter_state["waiters"] = waiters
            effective_budget = self._synchronize_capacity(
                pool_file, has_waiters=bool(waiters)
            )
            effective_floor, effective_ceiling = fit_request_to_budget(
                floor,
                ceiling,
                effective_budget,
                exact=exact,
                capacity_is_explicit=self._capacity_is_explicit,
            )
            own_entry = find_waiter(waiters, self._waiter_ticket)
            if self._waiter_ticket is not None and own_entry is None:
                self._waiter_ticket = None

            candidate_ticket = int(waiter_state["next_ticket"])
            candidate = {
                "ticket": candidate_ticket,
                "floor": effective_floor,
                "backfills": 0,
            }
            policy_waiters = list(waiters)
            if own_entry is None and queue_waiter:
                policy_waiters.append(candidate)
                own_entry = candidate
            elif own_entry is not None:
                own_entry["floor"] = effective_floor

            # Lock the currently free tokens as a consistent snapshot while the
            # pool lock excludes other acquisitions. Releases may still add
            # tokens, but no contender can spend a token before this decision.
            token_files, holders = try_acquire_tokens(
                self._directory, effective_budget, effective_budget
            )
            available = len(token_files)
            requester_ticket = (
                int(own_entry["ticket"]) if own_entry is not None else candidate_ticket
            )
            max_grant, backfilled_tickets = bounded_grant_limit(
                floor=effective_floor,
                ceiling=effective_ceiling,
                available=available,
                waiters=policy_waiters,
                requester_ticket=requester_ticket,
            )

            if max_grant >= effective_floor:
                granted_files = token_files[:max_grant]
                release_token_files(token_files[max_grant:])
                token_files = granted_files
                ticket_to_remove = self._waiter_ticket
                self._token_files = token_files
                self._effective_budget = effective_budget
                try:
                    metadata = write_holder_metadata(
                        token_files,
                        floor=effective_floor,
                        ceiling=effective_ceiling,
                        budget=effective_budget,
                    )
                    self._lease_id = str(metadata["lease_id"])
                    self._started = float(metadata["started"])
                    self._set_descendant_environment()
                    _register_lease(self)

                    for entry in waiters:
                        if int(entry["ticket"]) in backfilled_tickets:
                            entry["backfills"] = int(entry["backfills"]) + 1
                    if ticket_to_remove is not None:
                        waiter_state["waiters"] = [
                            entry
                            for entry in waiters
                            if int(entry["ticket"]) != ticket_to_remove
                        ]
                    else:
                        waiter_state["waiters"] = waiters
                    if (
                        backfilled_tickets
                        or removed_dead_waiters
                        or ticket_to_remove is not None
                    ):
                        write_waiter_state(self._directory, waiter_state)
                    if ticket_to_remove is not None:
                        self._waiter_ticket = None
                    self.start_watchdog()
                except BaseException:
                    self._stop_watchdog()
                    _unregister_lease(self)
                    release_token_files(self._token_files)
                    self._token_files = []
                    self._effective_budget = None
                    self._lease_id = None
                    self._started = None
                    self._restore_descendant_environment()
                    raise
                return self.granted, available, holders

            release_token_files(token_files)
            if queue_waiter and self._waiter_ticket is None:
                identity = process_identity_token(os.getpid())
                if not identity:
                    if removed_dead_waiters:
                        write_waiter_state(self._directory, waiter_state)
                    raise pytest.UsageError(
                        "Cannot safely queue for pytest worker tokens because this "
                        "process identity is unavailable."
                    )
                waiter_state["next_ticket"] = candidate_ticket + 1
                waiter_state["waiters"].append(
                    {
                        **candidate,
                        "pid": os.getpid(),
                        "process_identity": identity,
                    }
                )
                self._waiter_ticket = candidate_ticket
                write_waiter_state(self._directory, waiter_state)
            elif removed_dead_waiters:
                write_waiter_state(self._directory, waiter_state)

            reclaim_wedged_holders(
                holders,
                self._signaled_leases,
                now=self._now(),
                stale=self._effective_stale_timeout(),
                max_hold=self._effective_max_hold(),
            )
            return 0, available, holders
        finally:
            fcntl.flock(pool_file.fileno(), fcntl.LOCK_UN)
            pool_file.close()

    def make_inheritable(self) -> None:
        """Keep every leased descriptor open across the runner's pytest exec."""
        if not self._token_files:
            raise RuntimeError("worker-token lease has not been acquired")
        for token_file in self._token_files:
            os.set_inheritable(token_file.fileno(), True)

    def adopt(
        self, token_files: list[IO[str]], *, lease_id: str, started: float
    ) -> None:
        """Take ownership of token descriptors this process inherited across exec.

        The other side of :meth:`make_inheritable`. The lease object that made
        the descriptors inheritable died with the runner's ``execv``; the flocks
        did not, so the exec'd process rebuilds a lease around them rather than
        acquiring a second grant. Callers are responsible for checking that this
        really is the pid that acquired.
        """
        self._token_files = token_files
        self._effective_budget = len(token_files)
        self._lease_id = lease_id
        self._started = started
        _register_lease(self)
        self.start_watchdog()

    def release(self) -> None:
        """Release every held token and restore inherited environment values."""
        self._stop_watchdog()
        self._watchdog_started = False
        with self._lock:
            token_files = self._token_files
            lease_id = self._lease_id
            if not token_files:
                self._restore_descendant_environment()
                return
            self._token_files = []
            self._effective_budget = None
            self._lease_id = None
            self._started = None
        _unregister_lease_id(lease_id)
        if lease_id is not None:
            remove_progress_sidecar(self._directory, lease_id)
        try:
            release_token_files(token_files)
        finally:
            self._restore_descendant_environment()

    def start_watchdog(self) -> None:
        """Release this grant if it stops making progress or outlives the cap."""
        interval = self._effective_watchdog_interval()
        if interval <= 0 or self._watchdog_started or not self._token_files:
            return
        self._watchdog_started = True
        self._watchdog_stop.clear()
        thread = threading.Thread(
            target=self._watchdog_loop,
            args=(interval,),
            name="sase-suite-gate-watchdog",
            daemon=True,
        )
        thread.start()

    def _stop_watchdog(self) -> None:
        self._watchdog_stop.set()

    def _watchdog_loop(self, interval: float) -> None:
        while not self._watchdog_stop.wait(interval):
            if self._own_grant_reclaimable():
                print(
                    reclaim_message(
                        os.getpid(),
                        self.granted,
                        self._own_reclaim_reason() or "stale-heartbeat",
                        action="released",
                        stale=self._effective_stale_timeout(),
                        max_hold=self._effective_max_hold(),
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                self.release()
                return

    def _own_grant_reclaimable(self) -> bool:
        return self._own_reclaim_reason() is not None

    def _own_reclaim_reason(self) -> str | None:
        started = self._started
        lease_id = self._lease_id
        if started is None or lease_id is None:
            return None
        sidecar = read_progress_sidecar(self._directory, lease_id)
        heartbeat = float(sidecar["heartbeat"]) if sidecar is not None else started
        return reclaim_reason_from_state(
            {"started": started, "heartbeat": heartbeat},
            now=self._now(),
            stale=self._effective_stale_timeout(),
            max_hold=self._effective_max_hold(),
        )

    def _effective_stale_timeout(self) -> float:
        if self._stale_timeout is None:
            return holder_stale_timeout()
        return self._stale_timeout

    def _effective_max_hold(self) -> float:
        if self._max_hold is None:
            return holder_max_hold()
        return self._max_hold

    def _effective_watchdog_interval(self) -> float:
        if self._watchdog_interval is None:
            return holder_watchdog_interval()
        return self._watchdog_interval

    def refresh_heartbeat(self, heartbeat: float, progress: int) -> None:
        """Stamp this lease's own tokens with the caller's latest progress."""
        with self._lock:
            token_files = list(self._token_files)
            lease_id = self._lease_id
        if not token_files or lease_id is None:
            return
        refresh_token_heartbeats(token_files, heartbeat, progress)

    def _synchronize_capacity(
        self, pool_file: IO[str], *, has_waiters: bool = False
    ) -> int:
        stored_capacity = read_pool_capacity(pool_file)
        scan_limit = max(self._budget, stored_capacity or 0)
        active_holders = scan_active_holders(self._directory, scan_limit)

        if not active_holders and not has_waiters:
            write_pool_capacity(
                pool_file, self._budget, explicit=self._capacity_is_explicit
            )
            return self._budget

        if stored_capacity is None:
            raise pytest.UsageError(
                "The active pytest worker-token pool has missing or malformed "
                "capacity metadata. Wait for its holders to exit, then remove "
                f"{self._directory} before retrying."
            )
        if self._capacity_is_explicit and stored_capacity != self._budget:
            raise pytest.UsageError(
                "SASE_TEST_GATE_SLOTS requests "
                f"{self._budget} worker tokens, but the active pool was started "
                f"with {stored_capacity}. Wait for current holders to exit or "
                "use the active capacity before retrying."
            )
        return stored_capacity

    def _cancel_waiter_ticket(self) -> None:
        """Remove this live process's queue entry after timeout or cancellation."""
        ticket = self._waiter_ticket
        if ticket is None:
            return
        pool_file = (self._directory / POOL_FILE_NAME).open("a+", encoding="utf-8")
        try:
            fcntl.flock(pool_file.fileno(), fcntl.LOCK_EX)
            state = read_waiter_state(self._directory)
            waiters, removed_dead_waiters = remove_dead_waiters(state["waiters"])
            remaining = [entry for entry in waiters if int(entry["ticket"]) != ticket]
            if len(remaining) != len(state["waiters"]) or removed_dead_waiters:
                state["waiters"] = remaining
                write_waiter_state(self._directory, state)
        finally:
            self._waiter_ticket = None
            fcntl.flock(pool_file.fileno(), fcntl.LOCK_UN)
            pool_file.close()

    def _set_descendant_environment(self) -> None:
        """Mark descendants exempt, and say *why* they are exempt.

        Both variables, unconditionally. ``DISABLED_ENV`` alone keeps a nested
        pytest from deadlocking on tokens this process already holds, but it is
        the same string anyone can export at top level; ``GOVERNED_ENV`` is
        what distinguishes a demand a real lease already paid for from a claim
        that it did. A lease that set only the first would make its own children
        indistinguishable from an unaccounted run.
        """
        self._previous_environment = {
            name: os.environ.get(name) for name in LEASE_ENV_NAMES
        }
        os.environ[DISABLED_ENV] = "1"
        os.environ[GOVERNED_ENV] = "1"
        if self._lease_id is not None:
            os.environ[LEASE_ID_ENV] = self._lease_id
        os.environ[LEASE_PID_ENV] = str(os.getpid())
        os.environ[FDS_ENV] = ",".join(
            str(token_file.fileno()) for token_file in self._token_files
        )

    def _restore_descendant_environment(self) -> None:
        for name, previous_value in self._previous_environment.items():
            if previous_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous_value
        self._previous_environment.clear()


def _register_lease(lease: WorkerTokenLease) -> None:
    """Make ``lease`` findable by :func:`lease_by_id` for its lifetime."""
    if lease._lease_id is not None:
        _leases_by_id[lease._lease_id] = lease


def _unregister_lease(lease: WorkerTokenLease) -> None:
    """Drop ``lease`` from the registry."""
    _unregister_lease_id(lease._lease_id)


def _unregister_lease_id(lease_id: str | None) -> None:
    """Drop ``lease_id`` from the registry if it still names its own lease."""
    if lease_id is None:
        return
    current = _leases_by_id.get(lease_id)
    if current is not None and current._lease_id == lease_id:
        _leases_by_id.pop(lease_id, None)


def lease_by_id(lease_id: str) -> WorkerTokenLease | None:
    """Return the live lease with this id, or ``None`` if it is not ours.

    A nested pytest child inherits ``SASE_TEST_GATE_LEASE_ID`` but not the
    lease object behind it, so a miss here is ordinary: the child records its
    progress in the sidecar and leaves the token files to the owner.
    """
    return _leases_by_id.get(lease_id)
