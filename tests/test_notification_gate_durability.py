"""Atomic-write durability coverage for notification-gate files."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from sase.notification_gates.durability import atomic_write_json, file_lock
from sase.notification_gates.models import GateError


def test_gate_writer_reaps_only_targeted_stale_temp_siblings(tmp_path: Path) -> None:
    target = tmp_path / "request.json"
    stale = tmp_path / ".request.json.old.tmp"
    fresh = tmp_path / ".request.json.fresh.tmp"
    unrelated = tmp_path / ".response.json.old.tmp"
    for path in (stale, fresh, unrelated):
        path.write_text("temp", encoding="utf-8")
    old = time.time() - 25 * 60 * 60
    os.utime(stale, (old, old))
    os.utime(unrelated, (old, old))

    atomic_write_json(target, {"ok": True})

    assert not stale.exists()
    assert fresh.exists()
    assert unrelated.exists()


def test_file_lock_times_out_instead_of_blocking_indefinitely(tmp_path: Path) -> None:
    lock_path = tmp_path / ".response.lock"
    holder_ready = threading.Event()
    release_holder = threading.Event()

    def _hold_lock() -> None:
        with file_lock(lock_path):
            holder_ready.set()
            release_holder.wait(timeout=5)

    holder = threading.Thread(target=_hold_lock)
    holder.start()
    try:
        assert holder_ready.wait(timeout=5)

        started = time.monotonic()
        with pytest.raises(GateError) as excinfo:
            with file_lock(lock_path, timeout=0.2):
                pass
        elapsed = time.monotonic() - started
    finally:
        release_holder.set()
        holder.join(timeout=5)

    assert excinfo.value.code == "lock_timeout"
    assert elapsed < 2.0


def test_file_lock_with_no_timeout_still_blocks_until_released(tmp_path: Path) -> None:
    lock_path = tmp_path / ".response.lock"
    holder_ready = threading.Event()

    def _hold_briefly() -> None:
        with file_lock(lock_path):
            holder_ready.set()
            time.sleep(0.2)

    holder = threading.Thread(target=_hold_briefly)
    holder.start()
    try:
        assert holder_ready.wait(timeout=5)
        with file_lock(lock_path):
            pass
    finally:
        holder.join(timeout=5)
