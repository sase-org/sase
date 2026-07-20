"""Host-global concurrency gate for parallel pytest suite runs."""

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


_DEFAULT_SLOTS = 2
_DEFAULT_TIMEOUT_SECONDS = 45 * 60
_POLL_INTERVAL_SECONDS = 2.0
_STATUS_INTERVAL_SECONDS = 30.0
_CONFIG_ATTRIBUTE = "_sase_suite_gate"


class SuiteGate:
    """A crash-safe counting semaphore backed by advisory file locks."""

    def __init__(
        self,
        directory: Path,
        slots: int,
        timeout: float,
        *,
        poll_interval: float = _POLL_INTERVAL_SECONDS,
        status_interval: float = _STATUS_INTERVAL_SECONDS,
    ) -> None:
        self._directory = directory
        self._slots = slots
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._status_interval = status_interval
        self._slot_file: IO[str] | None = None
        self._previous_disabled_value: str | None = None
        self._disabled_was_set = False

    def acquire(self) -> None:
        """Wait for and acquire one suite slot."""
        self._directory.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._timeout
        next_status = time.monotonic() + self._status_interval

        while True:
            holders: dict[Path, str] = {}
            for slot_number in range(self._slots):
                slot_path = self._directory / f"slot-{slot_number}.lock"
                slot_file, metadata = _try_acquire_slot(slot_path)
                if slot_file is None:
                    holders[slot_path] = metadata
                    continue

                self._slot_file = slot_file
                _write_holder_metadata(slot_file)
                self._disabled_was_set = "SASE_TEST_GATE_DISABLED" in os.environ
                self._previous_disabled_value = os.environ.get(
                    "SASE_TEST_GATE_DISABLED"
                )
                os.environ["SASE_TEST_GATE_DISABLED"] = "1"
                return

            now = time.monotonic()
            if now >= deadline:
                holder_summary = _format_holders(holders)
                raise pytest.UsageError(
                    "Timed out waiting for a SASE parallel test-suite slot after "
                    f"{self._timeout:g}s. Current holders: {holder_summary}. "
                    "Adjust SASE_TEST_GATE_TIMEOUT or SASE_TEST_GATE_SLOTS, or "
                    "set SASE_TEST_GATE_DISABLED=1 to bypass the gate deliberately."
                )

            if now >= next_status:
                print(
                    "Waiting for a SASE parallel test-suite slot; current holders: "
                    f"{_format_holders(holders)}",
                    file=sys.stderr,
                    flush=True,
                )
                next_status = now + self._status_interval

            time.sleep(min(self._poll_interval, max(0.0, deadline - now)))

    def release(self) -> None:
        """Release the held slot and restore the inherited disable marker."""
        if self._slot_file is None:
            return

        try:
            fcntl.flock(self._slot_file.fileno(), fcntl.LOCK_UN)
        finally:
            self._slot_file.close()
            self._slot_file = None
            if self._disabled_was_set:
                assert self._previous_disabled_value is not None
                os.environ["SASE_TEST_GATE_DISABLED"] = self._previous_disabled_value
            else:
                os.environ.pop("SASE_TEST_GATE_DISABLED", None)


def configure_suite_gate(config: pytest.Config) -> None:
    """Acquire a gate slot when ``config`` represents an xdist controller."""
    if not _should_gate(config):
        return

    gate = SuiteGate(
        directory=_gate_directory(),
        slots=_positive_int_env("SASE_TEST_GATE_SLOTS", _DEFAULT_SLOTS),
        timeout=_non_negative_float_env(
            "SASE_TEST_GATE_TIMEOUT", _DEFAULT_TIMEOUT_SECONDS
        ),
    )
    gate.acquire()
    setattr(config, _CONFIG_ATTRIBUTE, gate)


def unconfigure_suite_gate(config: pytest.Config) -> None:
    """Release a gate slot previously acquired for ``config``."""
    gate = getattr(config, _CONFIG_ATTRIBUTE, None)
    if not isinstance(gate, SuiteGate):
        return
    gate.release()
    delattr(config, _CONFIG_ATTRIBUTE)


def _should_gate(config: pytest.Config) -> bool:
    if os.environ.get("SASE_TEST_GATE_DISABLED") == "1":
        return False
    if "PYTEST_XDIST_WORKER" in os.environ:
        return False

    numprocesses = getattr(config.option, "numprocesses", None)
    return numprocesses not in (None, 0, 1, "0", "1")


def _gate_directory() -> Path:
    configured = os.environ.get("SASE_TEST_GATE_DIR")
    if configured:
        return Path(configured)
    return Path(f"/tmp/sase-suite-gate-{os.getuid()}")


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
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


def _try_acquire_slot(slot_path: Path) -> tuple[IO[str] | None, str]:
    slot_file = slot_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(slot_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno not in (errno.EACCES, errno.EAGAIN):
            slot_file.close()
            raise
        slot_file.seek(0)
        metadata = slot_file.read()
        slot_file.close()
        return None, metadata
    return slot_file, ""


def _write_holder_metadata(slot_file: IO[str]) -> None:
    metadata = {
        "argv": shlex.join(sys.argv),
        "pid": os.getpid(),
        "started": time.time(),
    }
    slot_file.seek(0)
    slot_file.truncate()
    json.dump(metadata, slot_file, sort_keys=True)
    slot_file.write("\n")
    slot_file.flush()


def _format_holders(holders: dict[Path, str]) -> str:
    if not holders:
        return "unknown"
    return "; ".join(
        f"{slot_path.name}: {_format_holder(metadata)}"
        for slot_path, metadata in sorted(holders.items())
    )


def _format_holder(metadata: str) -> str:
    try:
        parsed: Any = json.loads(metadata)
        pid = int(parsed["pid"])
        started = float(parsed["started"])
        argv = str(parsed["argv"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return "holder metadata unavailable"

    age_seconds = max(0, round(time.time() - started))
    return f"pid {pid}, age {age_seconds}s, argv {argv!r}"
