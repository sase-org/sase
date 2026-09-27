"""Tests for the durable update-attempt journal facade."""

from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

import pytest

from sase.ace import update_attempts
from sase.ace.update_attempts import (
    UpdateAttemptOwner,
    begin_update_attempt,
    _current_owner,
    dismiss_update_failure,
    load_update_attempts,
    new_update_attempt,
    _owner_is_alive,
    settle_update_attempt,
)


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    return tmp_path / ".sase"


def _journal_file(home: Path) -> Path:
    return home / "update_attempts.json"


def test_begin_and_settle_round_trip(isolated_home: Path) -> None:
    attempt = new_update_attempt(
        label="update everything", proc_type="comprehensive-update", started_at=1000.0
    )
    assert attempt.stage == "apply"

    begun = begin_update_attempt(attempt)
    assert begun.failure is None
    assert begun.revision == 1

    stored = json.loads(_journal_file(isolated_home).read_text(encoding="utf-8"))
    assert stored["schema"] == 1
    assert stored["revision"] == 1
    assert [m["attempt_id"] for m in stored["in_flight"]] == [attempt.attempt_id]

    loaded = load_update_attempts()
    assert loaded.revision == 1  # own marker survives reconciliation
    assert loaded.failure is None

    settled = settle_update_attempt(
        attempt, success=False, error="boom\nsecond", output="out"
    )
    assert settled.failure is not None
    assert settled.failure.error == "boom"
    assert settled.failure.interrupted is False
    assert settled.revision == 2

    dismissed = dismiss_update_failure(attempt.attempt_id)
    assert dismissed.failure is None


def test_success_clears_earlier_failure(isolated_home: Path) -> None:
    _ = isolated_home
    base = time.time()
    failed_attempt = new_update_attempt(
        label="plan update", proc_type="update-preview", started_at=base
    )
    failed = settle_update_attempt(
        failed_attempt, success=False, error="boom", output=None
    )
    assert failed.failure is not None

    fixed_attempt = new_update_attempt(
        label="update everything",
        proc_type="comprehensive-update",
        started_at=base + 10.0,
    )
    cleared = settle_update_attempt(
        fixed_attempt, success=True, error=None, output=None
    )
    assert cleared.failure is None


def test_malformed_file_reads_empty_and_next_write_repairs(
    isolated_home: Path,
) -> None:
    path = _journal_file(isolated_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    assert load_update_attempts().failure is None

    attempt = new_update_attempt(
        label="update everything", proc_type="comprehensive-update", started_at=1000.0
    )
    begun = begin_update_attempt(attempt)
    assert begun.revision == 1
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["schema"] == 1


def test_foreign_schema_is_never_overwritten(isolated_home: Path) -> None:
    path = _journal_file(isolated_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    foreign = {"schema": 2, "revision": 9, "future": True}
    path.write_text(json.dumps(foreign), encoding="utf-8")

    assert load_update_attempts() == update_attempts.UpdateAttemptsView(
        revision=0, failure=None
    )
    attempt = new_update_attempt(
        label="update everything", proc_type="comprehensive-update", started_at=1000.0
    )
    assert begin_update_attempt(attempt).failure is None
    assert json.loads(path.read_text(encoding="utf-8")) == foreign


def test_lock_timeout_degrades_to_in_memory_view(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _journal_file(isolated_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    monkeypatch.setattr(update_attempts, "_LOCK_TIMEOUT_SECONDS", 0.2)
    with lock_path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            attempt = new_update_attempt(
                label="update everything",
                proc_type="comprehensive-update",
                started_at=1000.0,
            )
            view = begin_update_attempt(attempt)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    assert view.failure is None
    assert not path.exists()


def test_owner_is_alive_covers_execv_and_dead_pids() -> None:
    assert _owner_is_alive(_current_owner()) is True

    same_pid_other_instance = UpdateAttemptOwner(
        pid=os.getpid(), identity="old:1", instance_id="previous-incarnation"
    )
    assert _owner_is_alive(same_pid_other_instance) is False

    dead = UpdateAttemptOwner(pid=2**30, identity="", instance_id="long-gone")
    assert _owner_is_alive(dead) is False


def test_file_override_redirects_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "custom.json"
    monkeypatch.setattr(update_attempts, "_UPDATE_ATTEMPTS_FILE", override)
    attempt = new_update_attempt(
        label="update everything", proc_type="comprehensive-update", started_at=1000.0
    )
    assert begin_update_attempt(attempt).revision == 1
    assert override.exists()
