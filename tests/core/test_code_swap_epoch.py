"""The light code-swap epoch probes read the real lock and stamp files."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sase.core import code_swap_epoch
from sase.core.code_swap_epoch import (
    code_swap_in_play,
    code_swap_since_boot,
    code_swap_writer_live,
    long_lived_swap_guard,
    snapshot_boot_swap_generation,
    wait_for_code_swap_writer,
)
from sase.dev_update import code_swap_lock, code_swap_stamp
from sase.dev_update.code_swap_lock import code_swap_writer_lock


@pytest.fixture
def sase_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.delenv("SASE_DISABLE_CODE_SWAP_LOCK", raising=False)
    monkeypatch.setattr(code_swap_epoch, "_boot_epoch", None)
    return home


def _swap() -> None:
    with code_swap_writer_lock() as lock:
        assert lock.acquired


def _write_stamp(home: Path, **fields: object) -> None:
    locks = home / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    (locks / "code-swap-last.json").write_text(json.dumps(fields), encoding="utf-8")


def test_mirrored_names_match_the_dev_update_modules() -> None:
    assert code_swap_epoch._LOCK_FILENAME == code_swap_lock.CODE_SWAP_LOCK_FILENAME
    assert (
        code_swap_epoch._STAMP_FILENAME == code_swap_stamp.CODE_SWAP_LAST_SWAP_FILENAME
    )
    assert code_swap_epoch._GRACE_SECONDS == code_swap_stamp.CODE_SWAP_GRACE_SECONDS
    assert code_swap_epoch._ENV_DISABLE == code_swap_lock.ENV_DISABLE_CODE_SWAP_LOCK


def test_no_swap_on_record_reads_as_nothing_in_play(sase_home: Path) -> None:
    snapshot_boot_swap_generation()

    assert code_swap_writer_live() is False
    assert code_swap_since_boot() is False
    assert code_swap_in_play() is None
    assert long_lived_swap_guard()() is False


def test_live_writer_is_in_play(sase_home: Path) -> None:
    with code_swap_writer_lock() as lock:
        assert lock.acquired
        assert code_swap_writer_live() is True
        assert code_swap_in_play() == "a code swap is in progress"
    assert code_swap_writer_live() is False


def test_dead_writer_payload_is_not_a_live_writer(sase_home: Path) -> None:
    locks = sase_home / "locks"
    locks.mkdir(parents=True)
    (locks / "code-swap-v2.lock").write_text(
        json.dumps({"pid": 2**22 + 12345, "op": "dev.update"}), encoding="utf-8"
    )

    assert code_swap_writer_live() is False


def test_swap_after_boot_is_detected_and_one_before_boot_is_not(
    sase_home: Path,
) -> None:
    _swap()
    snapshot_boot_swap_generation()
    assert code_swap_since_boot() is False

    _swap()

    assert code_swap_since_boot() is True
    assert code_swap_in_play() == ("a code swap completed after this process started")


def test_boot_snapshot_is_taken_once(sase_home: Path) -> None:
    snapshot_boot_swap_generation()
    _swap()
    snapshot_boot_swap_generation()

    assert code_swap_since_boot() is True


def test_no_boot_snapshot_never_claims_a_swap_since_boot(sase_home: Path) -> None:
    _swap()

    assert code_swap_since_boot() is False


def test_snapshot_from_another_state_root_is_not_comparable(
    sase_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_boot_swap_generation()
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "other"))
    _swap()

    assert code_swap_since_boot() is False


def test_recent_swap_is_in_play_until_the_grace_expires(sase_home: Path) -> None:
    completed = datetime.now(UTC)
    _write_stamp(
        sase_home,
        op="dev.update",
        generation=3,
        started_at=(completed - timedelta(seconds=5)).isoformat(),
        completed_at=completed.isoformat(),
    )

    reason = code_swap_in_play(now=completed + timedelta(seconds=30))
    assert reason is not None
    assert "30s ago" in reason
    assert "120s post-swap grace" in reason
    assert code_swap_in_play(now=completed + timedelta(seconds=121)) is None


def test_corrupt_stamp_reads_as_no_swap(sase_home: Path) -> None:
    locks = sase_home / "locks"
    locks.mkdir(parents=True)
    (locks / "code-swap-last.json").write_text("{not json", encoding="utf-8")
    snapshot_boot_swap_generation()
    _write_stamp(sase_home, generation=True, completed_at="yesterday")

    assert code_swap_since_boot() is False
    assert code_swap_in_play() is None


def test_disabled_lock_reports_nothing(
    sase_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_boot_swap_generation()
    _swap()
    monkeypatch.setenv("SASE_DISABLE_CODE_SWAP_LOCK", "1")

    assert code_swap_since_boot() is False
    assert code_swap_in_play() is None


def test_long_lived_guard_trips_on_a_live_writer_and_after_a_swap(
    sase_home: Path,
) -> None:
    guard = long_lived_swap_guard()
    assert guard() is False

    with code_swap_writer_lock() as lock:
        assert lock.acquired
        assert guard() is True

    assert guard() is True
    assert long_lived_swap_guard()() is False


def test_wait_returns_true_once_the_writer_clears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = iter([True, True, False])
    monkeypatch.setattr(code_swap_epoch, "code_swap_writer_live", lambda: next(live))
    waits: list[str] = []
    sleeps: list[float] = []

    cleared = wait_for_code_swap_writer(
        timeout_seconds=60,
        poll_seconds=0.5,
        on_wait=lambda: waits.append("waiting"),
        sleep=sleeps.append,
        clock=lambda: 0.0,
    )

    assert cleared is True
    assert waits == ["waiting"]
    assert sleeps == [0.5, 0.5]


def test_wait_gives_up_at_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(code_swap_epoch, "code_swap_writer_live", lambda: True)
    ticks = iter([0.0, 5.0, 11.0])

    assert (
        wait_for_code_swap_writer(
            timeout_seconds=10,
            sleep=lambda _seconds: None,
            clock=lambda: next(ticks),
        )
        is False
    )


def test_probes_never_raise_on_an_unreadable_state_root(
    sase_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_subdir: str) -> Path:
        raise RuntimeError("no home")

    monkeypatch.setattr(code_swap_epoch, "sase_subdir", boom)
    snapshot_boot_swap_generation()

    assert code_swap_writer_live() is False
    assert code_swap_since_boot() is False
    assert code_swap_in_play() is None
    assert long_lived_swap_guard()() is False


def test_live_pid_check_handles_this_process() -> None:
    assert code_swap_epoch._pid_alive(os.getpid()) is True
