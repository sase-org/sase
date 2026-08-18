"""Host-global worker-token budget for parallel pytest suite runs."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import shlex
import signal
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import IO, Any

import pytest


_DEFAULT_TIMEOUT_SECONDS = 45 * 60
_POLL_INTERVAL_SECONDS = 2.0
_STATUS_INTERVAL_SECONDS = 30.0
# A live holder that stops completing work (no progress heartbeat) is treated
# as wedged. Thirty minutes is longer than any legitimate single test in this
# suite and far shorter than the 27-hour scoped run that motivated the bound.
_DEFAULT_STALE_SECONDS = 30 * 60
# Absolute backstop even while heartbeats continue. A full suite is minutes;
# four hours covers a loaded host without letting one grant sit overnight.
_DEFAULT_MAX_HOLD_SECONDS = 4 * 60 * 60
_DEFAULT_WATCHDOG_SECONDS = 30.0
_PROGRESS_WRITE_INTERVAL_SECONDS = 5.0
_DEFAULT_AUTOMATIC_FLOOR = 4
_DEFAULT_AUTOMATIC_CEILING = 28
_DEFAULT_AUTOMATIC_FAIR_SHARE_RUNS = 2
_DEFAULT_HARD_TOKEN_LIMIT = 32
# Reserve a proportion of the host rather than a flat count. A flat 4 is noise
# on the 64-core development host but is the entire machine on a 4-vCPU CI
# runner, where it collapsed the budget to one token and made the whole CI test
# matrix run serially.
_RESERVED_CPU_DIVISOR = 8
_MINIMUM_RESERVED_CPUS = 1
_RESERVED_MEMORY_KIB = 8 * 1024 * 1024
# Phase sase-ib.5 remeasured worker RSS after the footprint fixes at
# start=144292/post_collection=500632/median=500632/peak=500632 KiB in cost
# record 20260809T164811Z-3964960.json. Reserving 700 MiB per token keeps
# roughly 40% headroom over that peak while reflecting the measured curve.
_MEMORY_KIB_PER_WORKER = 700 * 1024
_MISSING_MEMORY_TOKEN_LIMIT = 4
_MEMINFO_PATH = Path("/proc/meminfo")
_CONFIG_ATTRIBUTE = "_sase_worker_token_lease"
_DISABLED_ENV = "SASE_TEST_GATE_DISABLED"
_GOVERNED_ENV = "SASE_TEST_GATE_GOVERNED"
_LEASE_ID_ENV = "SASE_TEST_GATE_LEASE_ID"
_LEASE_PID_ENV = "SASE_TEST_GATE_LEASE_PID"
_FDS_ENV = "SASE_TEST_GATE_FDS"
_LEASE_ENV_NAMES = (
    _DISABLED_ENV,
    _GOVERNED_ENV,
    _LEASE_ID_ENV,
    _LEASE_PID_ENV,
    _FDS_ENV,
)
_POOL_FILE_NAME = "pool.lock"
_leases_by_id: dict[str, WorkerTokenLease] = {}
_progress_last_write: dict[str, float] = {}
_progress_counts: dict[str, int] = {}


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
        self._token_files: list[IO[str]] = []
        self._previous_environment: dict[str, str | None] = {}
        self._effective_budget: int | None = None
        self._lease_id: str | None = None
        self._started: float | None = None
        self._lock = threading.Lock()
        self._watchdog_stop = threading.Event()
        self._watchdog_started = False
        self._signaled_leases: dict[str, int] = {}

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
        deadline = time.monotonic() + self._timeout
        next_status = time.monotonic() + self._status_interval

        while True:
            granted, last_available, last_holders = self._attempt(
                floor, ceiling, exact=exact
            )
            if granted:
                return granted

            now = time.monotonic()
            if now >= next_status:
                print(
                    _waiting_message(
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
                raise pytest.UsageError(
                    _timeout_message(
                        self._timeout,
                        floor,
                        ceiling,
                        last_available,
                        last_holders,
                        stale=self._effective_stale_timeout(),
                        max_hold=self._effective_max_hold(),
                    )
                )

            time.sleep(min(self._poll_interval, max(0.0, deadline - now)))

    def try_acquire(self, floor: int, ceiling: int) -> int:
        """Ask once for ``floor``..``ceiling`` tokens; return ``0`` if refused.

        The same atomic attempt :meth:`acquire` loops over, made exactly once.
        A caller that must never queue behind another agent's run — the
        diff-scoped lane's middle gear, whose whole promise is that it does not
        wait — asks with this instead and takes no for an answer.
        """
        self._prepare_request(floor, ceiling)
        granted, _available, _holders = self._attempt(floor, ceiling, exact=False)
        return granted

    def _prepare_request(self, floor: int, ceiling: int) -> None:
        if self._token_files:
            raise RuntimeError("worker-token lease is already acquired")
        if floor < 1 or ceiling < floor:
            raise ValueError("token floor and ceiling must be positive and ordered")
        self._directory.mkdir(parents=True, exist_ok=True)

    def _attempt(
        self, floor: int, ceiling: int, *, exact: bool
    ) -> tuple[int, int, dict[Path, str]]:
        """One pool-locked grant attempt: ``(granted, available, holders)``.

        ``granted`` is zero when the pool could not cover ``floor``; the
        remaining two describe what was in the way, which is what
        :meth:`acquire` prints while it waits.
        """
        pool_file = (self._directory / _POOL_FILE_NAME).open("a+", encoding="utf-8")
        try:
            fcntl.flock(pool_file.fileno(), fcntl.LOCK_EX)
            effective_budget = self._synchronize_capacity(pool_file)
            effective_floor, effective_ceiling = fit_request_to_budget(
                floor,
                ceiling,
                effective_budget,
                exact=exact,
                capacity_is_explicit=self._capacity_is_explicit,
            )
            token_files, holders = _try_acquire_tokens(
                self._directory, effective_budget, effective_ceiling
            )
            if len(token_files) >= effective_floor:
                self._token_files = token_files
                self._effective_budget = effective_budget
                try:
                    metadata = _write_holder_metadata(
                        token_files,
                        floor=effective_floor,
                        ceiling=effective_ceiling,
                        budget=effective_budget,
                    )
                    self._lease_id = str(metadata["lease_id"])
                    self._started = float(metadata["started"])
                    self._set_descendant_environment()
                    _register_lease(self)
                    self.start_watchdog()
                except BaseException:
                    self._stop_watchdog()
                    _unregister_lease(self)
                    _release_token_files(self._token_files)
                    self._token_files = []
                    self._effective_budget = None
                    self._lease_id = None
                    self._started = None
                    self._restore_descendant_environment()
                    raise
                return self.granted, len(token_files), holders
            _release_token_files(token_files)
            self._reclaim_holders(holders)
            return 0, len(token_files), holders
        finally:
            fcntl.flock(pool_file.fileno(), fcntl.LOCK_UN)
            pool_file.close()

    def make_inheritable(self) -> None:
        """Keep every leased descriptor open across the runner's pytest exec."""
        if not self._token_files:
            raise RuntimeError("worker-token lease has not been acquired")
        for token_file in self._token_files:
            os.set_inheritable(token_file.fileno(), True)

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
            _remove_progress_sidecar(self._directory, lease_id)
        try:
            _release_token_files(token_files)
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
                    _reclaim_message(
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
        sidecar = _read_progress_sidecar(self._directory, lease_id)
        heartbeat = float(sidecar["heartbeat"]) if sidecar is not None else started
        return _reclaim_reason_from_state(
            {"started": started, "heartbeat": heartbeat},
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

    def _refresh_holder_heartbeat(self, heartbeat: float, progress: int) -> None:
        with self._lock:
            token_files = list(self._token_files)
            lease_id = self._lease_id
        if not token_files or lease_id is None:
            return
        for token_file in token_files:
            try:
                token_file.seek(0)
                parsed: Any = json.load(token_file)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if not isinstance(parsed, dict):
                continue
            parsed["heartbeat"] = heartbeat
            parsed["progress"] = progress
            try:
                token_file.seek(0)
                token_file.truncate()
                json.dump(parsed, token_file, sort_keys=True)
                token_file.write("\n")
                token_file.flush()
            except OSError:
                continue

    def _reclaim_holders(self, holders: dict[Path, str]) -> None:
        seen: set[str] = set()
        for token_path, raw in holders.items():
            state = _load_holder_state(raw, token_path.parent)
            if state is None:
                continue
            lease_id = str(state["lease_id"])
            if lease_id in seen:
                continue
            seen.add(lease_id)
            reason = _reclaim_reason_from_state(
                state,
                stale=self._effective_stale_timeout(),
                max_hold=self._effective_max_hold(),
            )
            if reason is None:
                continue
            pid = int(state["pid"])
            previous = self._signaled_leases.get(lease_id)
            signum = signal.SIGKILL if previous == signal.SIGTERM else signal.SIGTERM
            if not _signal_holder(pid, state.get("starttime"), signum):
                continue
            self._signaled_leases[lease_id] = signum
            print(
                _reclaim_message(
                    pid,
                    int(state.get("granted", 1)),
                    reason,
                    action="signaled",
                    stale=self._effective_stale_timeout(),
                    max_hold=self._effective_max_hold(),
                ),
                file=sys.stderr,
                flush=True,
            )

    def _synchronize_capacity(self, pool_file: IO[str]) -> int:
        stored_capacity = _read_pool_capacity(pool_file)
        scan_limit = max(self._budget, stored_capacity or 0)
        active_holders = _scan_active_holders(self._directory, scan_limit)

        if not active_holders:
            _write_pool_capacity(
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

    def _set_descendant_environment(self) -> None:
        """Mark descendants exempt, and say *why* they are exempt.

        Both variables, unconditionally. ``_DISABLED_ENV`` alone keeps a nested
        pytest from deadlocking on tokens this process already holds, but it is
        the same string anyone can export at top level; ``_GOVERNED_ENV`` is
        what distinguishes a demand a real lease already paid for from a claim
        that it did. A lease that set only the first would make its own children
        indistinguishable from an unaccounted run.
        """
        self._previous_environment = {
            name: os.environ.get(name) for name in _LEASE_ENV_NAMES
        }
        os.environ[_DISABLED_ENV] = "1"
        os.environ[_GOVERNED_ENV] = "1"
        if self._lease_id is not None:
            os.environ[_LEASE_ID_ENV] = self._lease_id
        os.environ[_LEASE_PID_ENV] = str(os.getpid())
        os.environ[_FDS_ENV] = ",".join(
            str(token_file.fileno()) for token_file in self._token_files
        )

    def _restore_descendant_environment(self) -> None:
        for name, previous_value in self._previous_environment.items():
            if previous_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous_value
        self._previous_environment.clear()


def configured_token_budget() -> tuple[int, bool]:
    """Return the configured/computed host budget and whether it is explicit."""
    configured = os.environ.get("SASE_TEST_GATE_SLOTS")
    if configured is not None:
        return _positive_int("SASE_TEST_GATE_SLOTS", configured), True
    return (
        _calculate_default_token_budget(
            cpu_count=os.cpu_count(),
            mem_available_kib=_read_mem_available_kib(_MEMINFO_PATH),
        ),
        False,
    )


def automatic_worker_range(budget: int) -> tuple[int, int]:
    """Return the validated floor and ceiling for an automatic runner lease."""
    floor_raw = os.environ.get("SASE_PYTEST_WORKER_FLOOR")
    ceiling_raw = os.environ.get("SASE_PYTEST_WORKER_CEILING")
    floor = (
        min(_DEFAULT_AUTOMATIC_FLOOR, budget)
        if floor_raw is None
        else _positive_int("SASE_PYTEST_WORKER_FLOOR", floor_raw)
    )
    ceiling = (
        _default_automatic_ceiling(budget, floor)
        if ceiling_raw is None
        else _positive_int("SASE_PYTEST_WORKER_CEILING", ceiling_raw)
    )
    if floor > budget:
        raise pytest.UsageError(
            f"SASE_PYTEST_WORKER_FLOOR={floor} exceeds the {budget}-token "
            "host pool; lower the floor or increase SASE_TEST_GATE_SLOTS."
        )
    if ceiling > budget:
        raise pytest.UsageError(
            f"SASE_PYTEST_WORKER_CEILING={ceiling} exceeds the {budget}-token "
            "host pool; lower the ceiling or increase SASE_TEST_GATE_SLOTS."
        )
    if floor > ceiling:
        raise pytest.UsageError(
            "SASE_PYTEST_WORKER_FLOOR must be less than or equal to "
            "SASE_PYTEST_WORKER_CEILING."
        )
    return floor, ceiling


def _default_automatic_ceiling(budget: int, floor: int) -> int:
    # A controller cannot safely return tokens after xdist workers have
    # started: the pool would undercount live worker demand. Keep the default
    # grant to a peer-sized share up front, while explicit ceilings remain the
    # opt-in route for a deliberately wider single run.
    automatic_capacity = min(_DEFAULT_AUTOMATIC_CEILING, budget)
    fair_share = automatic_capacity // _DEFAULT_AUTOMATIC_FAIR_SHARE_RUNS
    return min(_DEFAULT_AUTOMATIC_CEILING, max(floor, fair_share))


def gate_directory() -> Path:
    """Return the shared token-pool directory for the current UID."""
    configured = os.environ.get("SASE_TEST_GATE_DIR")
    if configured:
        return Path(configured)
    return Path(f"/tmp/sase-pytest-tokens-{os.getuid()}")


def gate_timeout() -> float:
    """Return the configured bounded acquisition timeout."""
    return _non_negative_float_env("SASE_TEST_GATE_TIMEOUT", _DEFAULT_TIMEOUT_SECONDS)


def holder_stale_timeout() -> float:
    """Seconds without a progress heartbeat before a live holder is reclaimable.

    Zero disables stale-heartbeat reclaim. The waiter and the holder's
    watchdog both read this so tests can shrink the bound without changing
    the production default.
    """
    return _non_negative_float_env("SASE_TEST_GATE_STALE", _DEFAULT_STALE_SECONDS)


def holder_max_hold() -> float:
    """Absolute age after which a live holder is reclaimable even if progressing.

    Zero disables the age cap. This is the backstop for a grant that keeps
    writing heartbeats but never finishes.
    """
    return _non_negative_float_env("SASE_TEST_GATE_MAX_HOLD", _DEFAULT_MAX_HOLD_SECONDS)


def holder_watchdog_interval() -> float:
    """How often a holder checks its own grant for reclaim. Zero disables it."""
    return _non_negative_float_env("SASE_TEST_GATE_WATCHDOG", _DEFAULT_WATCHDOG_SECONDS)


def holder_reclaim_reason(
    metadata: str,
    *,
    now: float | None = None,
    directory: Path | None = None,
    stale: float | None = None,
    max_hold: float | None = None,
) -> str | None:
    """Return ``stale-heartbeat``, ``max-hold``, or ``None`` if the grant is healthy."""
    state = _load_holder_state(metadata, directory)
    if state is None:
        return None
    return _reclaim_reason_from_state(
        state,
        now=now,
        stale=holder_stale_timeout() if stale is None else stale,
        max_hold=holder_max_hold() if max_hold is None else max_hold,
    )


def record_lease_progress(event: str) -> None:
    """Record suite progress for the inherited or locally held worker-token grant.

    xdist workers skip this: the controller sees their forwarded reports and is
    the process whose pid matches the lease. Nested pytest subprocesses still
    write the sidecar — a child that is running tests *is* progress — but they
    cannot adopt the parent's flock.
    """
    if "PYTEST_XDIST_WORKER" in os.environ:
        return
    lease_id = os.environ.get(_LEASE_ID_ENV)
    if not lease_id:
        return
    now = time.time()
    last = _progress_last_write.get(lease_id, 0.0)
    if event == "call" and now - last < _PROGRESS_WRITE_INTERVAL_SECONDS:
        return
    progress = _progress_counts.get(lease_id, 0) + 1
    _progress_counts[lease_id] = progress
    _progress_last_write[lease_id] = now
    directory = gate_directory()
    _write_progress_sidecar(
        directory, lease_id, heartbeat=now, progress=progress, event=event
    )
    lease = _leases_by_id.get(lease_id)
    if lease is not None:
        lease._refresh_holder_heartbeat(now, progress)


def descendant_exemption() -> bool:
    """Report whether an ancestor's lease already accounts for this demand.

    The distinction the pool depends on. Every held lease marks its descendants
    with ``_GOVERNED_ENV``, and xdist marks its own workers, so either signal
    means the tokens for this width have already been taken by somebody above
    us — asking again would double-count the same demand. A bare
    ``_DISABLED_ENV`` is deliberately *not* corroboration: anyone can export it,
    and one that did is exactly how a ``-n 64`` run took a 64-worker share of a
    62 GiB host while holding zero tokens.
    """
    return os.environ.get(_GOVERNED_ENV) == "1" or "PYTEST_XDIST_WORKER" in os.environ


def configure_suite_gate(config: pytest.Config) -> None:
    """Acquire exact worker capacity for an ungoverned xdist controller."""
    if _is_gate_exempt():
        _adopt_inherited_lease(config)
        return

    requested_workers = _xdist_worker_count(config)
    if requested_workers is None:
        return
    budget, capacity_is_explicit = configured_token_budget()
    lease = WorkerTokenLease(
        directory=gate_directory(),
        budget=budget,
        timeout=gate_timeout(),
        capacity_is_explicit=capacity_is_explicit,
    )
    lease.acquire(requested_workers, requested_workers, exact=True)
    setattr(config, _CONFIG_ATTRIBUTE, lease)


def unconfigure_suite_gate(config: pytest.Config) -> None:
    """Release worker capacity previously acquired for ``config``."""
    lease = getattr(config, _CONFIG_ATTRIBUTE, None)
    if not isinstance(lease, WorkerTokenLease):
        return
    lease.release()
    delattr(config, _CONFIG_ATTRIBUTE)


def _calculate_default_token_budget(
    *, cpu_count: int | None, mem_available_kib: int | None
) -> int:
    if cpu_count is None or cpu_count < 1:
        cpu_limit = 1
    else:
        reserved_cpus = max(_MINIMUM_RESERVED_CPUS, cpu_count // _RESERVED_CPU_DIVISOR)
        cpu_limit = max(cpu_count - reserved_cpus, 1)

    if mem_available_kib is None:
        memory_limit = _MISSING_MEMORY_TOKEN_LIMIT
    else:
        worker_memory_kib = max(mem_available_kib - _RESERVED_MEMORY_KIB, 0)
        memory_limit = max(worker_memory_kib // _MEMORY_KIB_PER_WORKER, 1)

    return max(1, min(cpu_limit, memory_limit, _DEFAULT_HARD_TOKEN_LIMIT))


def _read_mem_available_kib(path: Path) -> int | None:
    try:
        meminfo = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None

    for line in meminfo.splitlines():
        key, separator, value = line.partition(":")
        if key != "MemAvailable" or not separator:
            continue
        fields = value.split()
        if len(fields) < 2 or fields[1].lower() != "kb":
            return None
        try:
            available_kib = int(fields[0])
        except ValueError:
            return None
        return available_kib if available_kib >= 0 else None
    return None


def _positive_int(name: str, raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise pytest.UsageError(f"{name} must be a positive integer") from error
    if value < 1:
        raise pytest.UsageError(f"{name} must be a positive integer")
    return value


def _non_negative_float_env(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as error:
        raise pytest.UsageError(f"{name} must be a non-negative number") from error
    if value < 0:
        raise pytest.UsageError(f"{name} must be a non-negative number")
    return value


def fit_request_to_budget(
    floor: int,
    ceiling: int,
    budget: int,
    *,
    exact: bool,
    capacity_is_explicit: bool,
) -> tuple[int, int]:
    """Clamp a floor/ceiling to ``budget``; refuse an over-budget exact ask.

    Public because the bypass path in ``tools/run_pytest`` bounds itself with
    the same arithmetic and the same error text as a real acquisition, rather
    than reimplementing either.
    """
    if exact and ceiling > budget:
        capacity_source = (
            "SASE_TEST_GATE_SLOTS" if capacity_is_explicit else "computed host budget"
        )
        raise pytest.UsageError(
            f"Requested {ceiling} pytest worker tokens, but the {capacity_source} "
            f"permits only {budget}. Reduce SASE_PYTEST_WORKERS/-n or increase "
            "SASE_TEST_GATE_SLOTS deliberately."
        )
    return min(floor, budget), min(ceiling, budget)


def _adopt_inherited_lease(config: pytest.Config) -> None:
    """Re-wrap exec-surviving token FDs so this process can watchdog and release.

    ``tools/run_pytest`` acquires, marks the descriptors inheritable, and
    ``execv``s into pytest. The lease object dies with the runner; the flocks
    do not. Only the same PID that acquired may adopt — xdist workers and
    nested pytest children inherit the FDs but have a different pid, so they
    must not unlock the controller's grant on exit.
    """
    if "PYTEST_XDIST_WORKER" in os.environ:
        return
    raw_pid = os.environ.get(_LEASE_PID_ENV)
    raw_fds = os.environ.get(_FDS_ENV)
    lease_id = os.environ.get(_LEASE_ID_ENV)
    if not raw_pid or not raw_fds or not lease_id:
        return
    try:
        if int(raw_pid) != os.getpid():
            return
        fds = [int(part) for part in raw_fds.split(",") if part]
    except ValueError:
        return
    if not fds:
        return
    token_files: list[IO[str]] = []
    try:
        token_files = [os.fdopen(fd, "r+", encoding="utf-8") for fd in fds]
    except OSError:
        _release_token_files(token_files)
        return
    lease = WorkerTokenLease(
        directory=gate_directory(),
        budget=max(len(token_files), 1),
        timeout=0.0,
    )
    lease._token_files = token_files
    lease._effective_budget = len(token_files)
    lease._lease_id = lease_id
    started = _started_from_token_files(token_files)
    lease._started = started if started is not None else time.time()
    _register_lease(lease)
    lease.start_watchdog()
    setattr(config, _CONFIG_ATTRIBUTE, lease)


def _started_from_token_files(token_files: list[IO[str]]) -> float | None:
    for token_file in token_files:
        try:
            token_file.seek(0)
            parsed: Any = json.load(token_file)
            return float(parsed["started"])
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return None


def _is_gate_exempt() -> bool:
    # The bare disable flag counts here, uncorroborated or not: this is the
    # in-pytest safety net, and a caller who deliberately disabled the gate must
    # not have it re-acquire underneath them. Bounding the *width* of such a run
    # is `tools/run_pytest`'s job, because that is the only place that chooses
    # one.
    return descendant_exemption() or os.environ.get(_DISABLED_ENV) == "1"


def _xdist_worker_count(config: pytest.Config) -> int | None:
    option = config.option
    tx = getattr(option, "tx", None)
    if tx:
        worker_count = len(tx)
    else:
        raw_count = getattr(option, "numprocesses", None)
        if raw_count in (None, 0, 1, "0", "1"):
            return None
        if raw_count in ("auto", "logical"):
            hook = getattr(config, "hook", None)
            if hook is None:
                raise pytest.UsageError(
                    f"Cannot resolve pytest-xdist -n {raw_count} safely; use a "
                    "positive numeric worker count."
                )
            worker_count = hook.pytest_xdist_auto_num_workers(config=config)
        else:
            try:
                worker_count = int(raw_count)
            except (TypeError, ValueError) as error:
                raise pytest.UsageError(
                    f"Cannot resolve pytest-xdist worker request {raw_count!r}; "
                    "use a positive numeric count, auto, or logical."
                ) from error

        max_processes = getattr(option, "maxprocesses", None)
        if max_processes:
            worker_count = min(worker_count, int(max_processes))

    if worker_count <= 1:
        return None
    return worker_count


def _read_pool_capacity(pool_file: IO[str]) -> int | None:
    pool_file.seek(0)
    try:
        parsed: Any = json.load(pool_file)
        capacity = int(parsed["capacity"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return capacity if capacity > 0 else None


def _write_pool_capacity(pool_file: IO[str], capacity: int, *, explicit: bool) -> None:
    metadata = {
        "capacity": capacity,
        "explicit": explicit,
        "updated": time.time(),
    }
    pool_file.seek(0)
    pool_file.truncate()
    json.dump(metadata, pool_file, sort_keys=True)
    pool_file.write("\n")
    pool_file.flush()


def _token_path(directory: Path, token_number: int) -> Path:
    return directory / f"token-{token_number:03d}.lock"


def _scan_active_holders(directory: Path, limit: int) -> dict[Path, str]:
    holders: dict[Path, str] = {}
    for token_number in range(limit):
        token_path = _token_path(directory, token_number)
        token_file, metadata = _try_acquire_token(token_path)
        if token_file is None:
            holders[token_path] = metadata
        else:
            token_file.close()
    return holders


def _try_acquire_tokens(
    directory: Path, budget: int, ceiling: int
) -> tuple[list[IO[str]], dict[Path, str]]:
    token_files: list[IO[str]] = []
    holders: dict[Path, str] = {}
    for token_number in range(budget):
        token_path = _token_path(directory, token_number)
        token_file, metadata = _try_acquire_token(token_path)
        if token_file is None:
            holders[token_path] = metadata
            continue
        token_files.append(token_file)
        if len(token_files) == ceiling:
            break
    return token_files, holders


def _try_acquire_token(token_path: Path) -> tuple[IO[str] | None, str]:
    token_file = token_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(token_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno not in (errno.EACCES, errno.EAGAIN):
            token_file.close()
            raise
        token_file.seek(0)
        metadata = token_file.read()
        token_file.close()
        return None, metadata
    return token_file, ""


def _write_holder_metadata(
    token_files: list[IO[str]], *, floor: int, ceiling: int, budget: int
) -> dict[str, Any]:
    started = time.time()
    metadata: dict[str, Any] = {
        "argv": shlex.join(sys.argv),
        "budget": budget,
        "granted": len(token_files),
        "heartbeat": started,
        "lease_id": f"{os.getpid()}-{time.time_ns()}",
        "pid": os.getpid(),
        "progress": 0,
        "requested_ceiling": ceiling,
        "requested_floor": floor,
        "started": started,
        "starttime": _process_starttime(os.getpid()),
    }
    for token_file in token_files:
        token_file.seek(0)
        token_file.truncate()
        json.dump(metadata, token_file, sort_keys=True)
        token_file.write("\n")
        token_file.flush()
    return metadata


def _release_token_files(token_files: list[IO[str]]) -> None:
    first_error: BaseException | None = None
    for token_file in token_files:
        try:
            fcntl.flock(token_file.fileno(), fcntl.LOCK_UN)
        except BaseException as error:  # pragma: no cover - defensive cleanup
            first_error = first_error or error
        try:
            token_file.close()
        except BaseException as error:  # pragma: no cover - defensive cleanup
            first_error = first_error or error
    if first_error is not None:
        raise first_error


def _request_description(floor: int, ceiling: int) -> str:
    if floor == ceiling:
        return f"{floor} worker tokens"
    return f"{floor}-{ceiling} worker tokens"


def _waiting_message(
    floor: int,
    ceiling: int,
    available: int,
    holders: dict[Path, str],
    *,
    stale: float | None = None,
    max_hold: float | None = None,
) -> str:
    return (
        "Waiting for a SASE pytest worker-token grant of "
        f"{_request_description(floor, ceiling)}; {available} tokens were "
        f"available below the floor. Current holders: "
        f"{_format_holders(holders, stale=stale, max_hold=max_hold)}"
    )


def _timeout_message(
    timeout: float,
    floor: int,
    ceiling: int,
    available: int,
    holders: dict[Path, str],
    *,
    stale: float | None = None,
    max_hold: float | None = None,
) -> str:
    return (
        "Timed out waiting for a SASE pytest worker-token grant of "
        f"{_request_description(floor, ceiling)} after {timeout:g}s; "
        f"{available} tokens were available below the floor. Current holders: "
        f"{_format_holders(holders, stale=stale, max_hold=max_hold)}. "
        "Adjust SASE_TEST_GATE_TIMEOUT, SASE_TEST_GATE_SLOTS, "
        "SASE_TEST_GATE_STALE, SASE_TEST_GATE_MAX_HOLD, "
        "SASE_PYTEST_WORKER_FLOOR, or SASE_PYTEST_WORKER_CEILING; set "
        "SASE_TEST_GATE_DISABLED=1 only to bypass the pool deliberately."
    )


def _format_holders(
    holders: dict[Path, str],
    *,
    stale: float | None = None,
    max_hold: float | None = None,
) -> str:
    if not holders:
        return "unknown"

    directory = next(iter(holders)).parent
    grouped: dict[str, tuple[int, str]] = {}
    for metadata in holders.values():
        key, formatted = _holder_identity_and_text(
            metadata, directory=directory, stale=stale, max_hold=max_hold
        )
        count, _ = grouped.get(key, (0, formatted))
        grouped[key] = (count + 1, formatted)
    return "; ".join(
        f"{count} token{'s' if count != 1 else ''}: {formatted}"
        for count, formatted in sorted(grouped.values(), key=lambda item: item[1])
    )


def _holder_identity_and_text(
    metadata: str,
    *,
    directory: Path | None = None,
    stale: float | None = None,
    max_hold: float | None = None,
) -> tuple[str, str]:
    state = _load_holder_state(metadata, directory)
    if state is None:
        return f"unavailable-{metadata}", "holder metadata unavailable"

    now = time.time()
    age_seconds = max(0, round(now - float(state["started"])))
    heartbeat_seconds = max(0, round(now - float(state["heartbeat"])))
    reason = _reclaim_reason_from_state(
        state,
        now=now,
        stale=holder_stale_timeout() if stale is None else stale,
        max_hold=holder_max_hold() if max_hold is None else max_hold,
    )
    reclaimable = f", {reason}" if reason is not None else ""
    return (
        str(state["lease_id"]),
        (
            f"pid {int(state['pid'])}, grant {int(state['granted'])}, "
            f"age {age_seconds}s, heartbeat {heartbeat_seconds}s, "
            f"argv {state['argv']!r}{reclaimable}"
        ),
    )


def _load_holder_state(metadata: str, directory: Path | None) -> dict[str, Any] | None:
    try:
        parsed: Any = json.loads(metadata)
        pid = int(parsed["pid"])
        started = float(parsed["started"])
        argv = str(parsed["argv"])
        lease_id = str(parsed.get("lease_id", f"{pid}-{started}-{argv}"))
        granted = int(parsed.get("granted", 1))
        heartbeat = float(parsed.get("heartbeat", started))
        starttime = parsed.get("starttime")
        if starttime is not None:
            starttime = int(starttime)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    if directory is not None:
        sidecar = _read_progress_sidecar(directory, lease_id)
        if sidecar is not None:
            sidecar_heartbeat = float(sidecar["heartbeat"])
            if sidecar_heartbeat > heartbeat:
                heartbeat = sidecar_heartbeat

    return {
        "argv": argv,
        "granted": granted,
        "heartbeat": heartbeat,
        "lease_id": lease_id,
        "pid": pid,
        "started": started,
        "starttime": starttime,
    }


def _reclaim_reason_from_state(
    state: Mapping[str, Any],
    *,
    now: float | None = None,
    stale: float,
    max_hold: float,
) -> str | None:
    current = time.time() if now is None else now
    started = float(state["started"])
    heartbeat = float(state.get("heartbeat", started))
    if max_hold > 0 and current - started >= max_hold:
        return "max-hold"
    if stale > 0 and current - heartbeat >= stale:
        return "stale-heartbeat"
    return None


def _progress_sidecar_path(directory: Path, lease_id: str) -> Path:
    return directory / f"lease-{lease_id}.progress"


def _write_progress_sidecar(
    directory: Path,
    lease_id: str,
    *,
    heartbeat: float,
    progress: int,
    event: str,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = _progress_sidecar_path(directory, lease_id)
    payload = {
        "event": event,
        "heartbeat": heartbeat,
        "lease_id": lease_id,
        "progress": progress,
    }
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )
        tmp_path.replace(path)
    except OSError:
        tmp_path.unlink(missing_ok=True)


def _read_progress_sidecar(directory: Path, lease_id: str) -> dict[str, Any] | None:
    path = _progress_sidecar_path(directory, lease_id)
    try:
        parsed: Any = json.loads(path.read_text(encoding="utf-8"))
        heartbeat = float(parsed["heartbeat"])
        progress = int(parsed.get("progress", 0))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return {"heartbeat": heartbeat, "progress": progress}


def _remove_progress_sidecar(directory: Path, lease_id: str) -> None:
    path = _progress_sidecar_path(directory, lease_id)
    try:
        path.unlink()
    except OSError:
        pass
    _progress_last_write.pop(lease_id, None)
    _progress_counts.pop(lease_id, None)


def _register_lease(lease: WorkerTokenLease) -> None:
    if lease._lease_id is not None:
        _leases_by_id[lease._lease_id] = lease


def _unregister_lease(lease: WorkerTokenLease) -> None:
    _unregister_lease_id(lease._lease_id)


def _unregister_lease_id(lease_id: str | None) -> None:
    if lease_id is None:
        return
    current = _leases_by_id.get(lease_id)
    if current is not None and current._lease_id == lease_id:
        _leases_by_id.pop(lease_id, None)


def _process_starttime(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    rparen = stat.rfind(")")
    if rparen < 0:
        return None
    fields = stat[rparen + 2 :].split()
    try:
        return int(fields[19])
    except (IndexError, ValueError):
        return None


def _signal_holder(pid: int, starttime: object, signum: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    live_starttime = _process_starttime(pid)
    if live_starttime is None:
        return False
    if starttime is not None and int(starttime) != live_starttime:
        return False
    try:
        os.kill(pid, signum)
    except OSError:
        return False
    return True


def _reclaim_message(
    pid: int,
    granted: int,
    reason: str,
    *,
    action: str,
    stale: float,
    max_hold: float,
) -> str:
    return (
        "Reclaiming a wedged SASE pytest worker-token grant: "
        f"{action} pid {pid}, {granted} token{'s' if granted != 1 else ''}, "
        f"{reason}. A live holder is bounded by SASE_TEST_GATE_STALE "
        f"({stale:g}s without progress) and "
        f"SASE_TEST_GATE_MAX_HOLD ({max_hold:g}s absolute)."
    )
