"""Host-global worker-token budget for parallel pytest suite runs."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import shlex
import sys
import time
from pathlib import Path
from typing import IO, Any

import pytest


_DEFAULT_TIMEOUT_SECONDS = 45 * 60
_POLL_INTERVAL_SECONDS = 2.0
_STATUS_INTERVAL_SECONDS = 30.0
_DEFAULT_AUTOMATIC_FLOOR = 4
_DEFAULT_AUTOMATIC_CEILING = 28
_DEFAULT_HARD_TOKEN_LIMIT = 32
_RESERVED_CPUS = 4
_RESERVED_MEMORY_KIB = 8 * 1024 * 1024
# A representative eight-worker run on the 64-GiB development host peaked at
# about 0.65 GiB RSS per worker plus 0.13 GiB for the controller. Reserving
# 1.2 GiB per token leaves nearly 2x worker headroom for heavier test files.
_MEMORY_KIB_PER_WORKER = 1229 * 1024
_MISSING_MEMORY_TOKEN_LIMIT = 4
_MEMINFO_PATH = Path("/proc/meminfo")
_CONFIG_ATTRIBUTE = "_sase_worker_token_lease"
_DISABLED_ENV = "SASE_TEST_GATE_DISABLED"
_GOVERNED_ENV = "SASE_TEST_GATE_GOVERNED"
_POOL_FILE_NAME = "pool.lock"


class WorkerTokenLease:
    """A crash-safe lease over several host-global pytest worker tokens."""

    def __init__(
        self,
        directory: Path,
        budget: int,
        timeout: float,
        *,
        capacity_is_explicit: bool = False,
        governed: bool = False,
        poll_interval: float = _POLL_INTERVAL_SECONDS,
        status_interval: float = _STATUS_INTERVAL_SECONDS,
    ) -> None:
        if budget < 1:
            raise ValueError("budget must be positive")
        self._directory = directory
        self._budget = budget
        self._timeout = timeout
        self._capacity_is_explicit = capacity_is_explicit
        self._governed = governed
        self._poll_interval = poll_interval
        self._status_interval = status_interval
        self._token_files: list[IO[str]] = []
        self._previous_environment: dict[str, str | None] = {}
        self._effective_budget: int | None = None

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
        if self._token_files:
            raise RuntimeError("worker-token lease is already acquired")
        if floor < 1 or ceiling < floor:
            raise ValueError("token floor and ceiling must be positive and ordered")

        self._directory.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._timeout
        next_status = time.monotonic() + self._status_interval
        last_holders: dict[Path, str] = {}
        last_available = 0

        while True:
            pool_file = (self._directory / _POOL_FILE_NAME).open("a+", encoding="utf-8")
            try:
                fcntl.flock(pool_file.fileno(), fcntl.LOCK_EX)
                effective_budget = self._synchronize_capacity(pool_file)
                effective_floor, effective_ceiling = _fit_request_to_budget(
                    floor,
                    ceiling,
                    effective_budget,
                    exact=exact,
                    capacity_is_explicit=self._capacity_is_explicit,
                )
                token_files, holders = _try_acquire_tokens(
                    self._directory, effective_budget, effective_ceiling
                )
                last_available = len(token_files)
                last_holders = holders
                if len(token_files) >= effective_floor:
                    self._token_files = token_files
                    self._effective_budget = effective_budget
                    try:
                        _write_holder_metadata(
                            token_files,
                            floor=effective_floor,
                            ceiling=effective_ceiling,
                            budget=effective_budget,
                        )
                        self._set_descendant_environment()
                    except BaseException:
                        _release_token_files(self._token_files)
                        self._token_files = []
                        self._effective_budget = None
                        self._restore_descendant_environment()
                        raise
                    return self.granted
                _release_token_files(token_files)
            finally:
                fcntl.flock(pool_file.fileno(), fcntl.LOCK_UN)
                pool_file.close()

            now = time.monotonic()
            if now >= next_status:
                print(
                    _waiting_message(floor, ceiling, last_available, last_holders),
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
                    )
                )

            time.sleep(min(self._poll_interval, max(0.0, deadline - now)))

    def make_inheritable(self) -> None:
        """Keep every leased descriptor open across the runner's pytest exec."""
        if not self._token_files:
            raise RuntimeError("worker-token lease has not been acquired")
        for token_file in self._token_files:
            os.set_inheritable(token_file.fileno(), True)

    def release(self) -> None:
        """Release every held token and restore inherited environment values."""
        if not self._token_files:
            return

        try:
            _release_token_files(self._token_files)
            self._token_files = []
            self._effective_budget = None
        finally:
            self._restore_descendant_environment()

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
        names = [_DISABLED_ENV]
        if self._governed:
            names.append(_GOVERNED_ENV)
        self._previous_environment = {name: os.environ.get(name) for name in names}
        os.environ[_DISABLED_ENV] = "1"
        if self._governed:
            os.environ[_GOVERNED_ENV] = "1"

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
        min(
            _DEFAULT_AUTOMATIC_CEILING,
            max(floor, budget - floor),
        )
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


def gate_directory() -> Path:
    """Return the shared token-pool directory for the current UID."""
    configured = os.environ.get("SASE_TEST_GATE_DIR")
    if configured:
        return Path(configured)
    return Path(f"/tmp/sase-pytest-tokens-{os.getuid()}")


def gate_timeout() -> float:
    """Return the configured bounded acquisition timeout."""
    return _non_negative_float_env("SASE_TEST_GATE_TIMEOUT", _DEFAULT_TIMEOUT_SECONDS)


def configure_suite_gate(config: pytest.Config) -> None:
    """Acquire exact worker capacity for an ungoverned xdist controller."""
    if _is_gate_exempt():
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
        cpu_limit = max(cpu_count - _RESERVED_CPUS, 1)

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


def _fit_request_to_budget(
    floor: int,
    ceiling: int,
    budget: int,
    *,
    exact: bool,
    capacity_is_explicit: bool,
) -> tuple[int, int]:
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


def _is_gate_exempt() -> bool:
    return (
        os.environ.get(_DISABLED_ENV) == "1"
        or os.environ.get(_GOVERNED_ENV) == "1"
        or "PYTEST_XDIST_WORKER" in os.environ
    )


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
) -> None:
    metadata = {
        "argv": shlex.join(sys.argv),
        "budget": budget,
        "granted": len(token_files),
        "lease_id": f"{os.getpid()}-{time.time_ns()}",
        "pid": os.getpid(),
        "requested_ceiling": ceiling,
        "requested_floor": floor,
        "started": time.time(),
    }
    for token_file in token_files:
        token_file.seek(0)
        token_file.truncate()
        json.dump(metadata, token_file, sort_keys=True)
        token_file.write("\n")
        token_file.flush()


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
) -> str:
    return (
        "Waiting for a SASE pytest worker-token grant of "
        f"{_request_description(floor, ceiling)}; {available} tokens were "
        f"available below the floor. Current holders: {_format_holders(holders)}"
    )


def _timeout_message(
    timeout: float,
    floor: int,
    ceiling: int,
    available: int,
    holders: dict[Path, str],
) -> str:
    return (
        "Timed out waiting for a SASE pytest worker-token grant of "
        f"{_request_description(floor, ceiling)} after {timeout:g}s; "
        f"{available} tokens were available below the floor. Current holders: "
        f"{_format_holders(holders)}. Adjust SASE_TEST_GATE_TIMEOUT, "
        "SASE_TEST_GATE_SLOTS, SASE_PYTEST_WORKER_FLOOR, or "
        "SASE_PYTEST_WORKER_CEILING; set SASE_TEST_GATE_DISABLED=1 only to "
        "bypass the pool deliberately."
    )


def _format_holders(holders: dict[Path, str]) -> str:
    if not holders:
        return "unknown"

    grouped: dict[str, tuple[int, str]] = {}
    for metadata in holders.values():
        key, formatted = _holder_identity_and_text(metadata)
        count, _ = grouped.get(key, (0, formatted))
        grouped[key] = (count + 1, formatted)
    return "; ".join(
        f"{count} token{'s' if count != 1 else ''}: {formatted}"
        for count, formatted in sorted(grouped.values(), key=lambda item: item[1])
    )


def _holder_identity_and_text(metadata: str) -> tuple[str, str]:
    try:
        parsed: Any = json.loads(metadata)
        pid = int(parsed["pid"])
        started = float(parsed["started"])
        argv = str(parsed["argv"])
        lease_id = str(parsed.get("lease_id", f"{pid}-{started}-{argv}"))
        granted = int(parsed.get("granted", 1))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return f"unavailable-{metadata}", "holder metadata unavailable"

    age_seconds = max(0, round(time.time() - started))
    return (
        lease_id,
        f"pid {pid}, grant {granted}, age {age_seconds}s, argv {argv!r}",
    )
