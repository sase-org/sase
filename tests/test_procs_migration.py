"""Tests for the one-shot ``~/.sase/tasks`` -> ``~/.sase/procs`` migration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sase.procs import get_proc, read_procs
from sase.procs._migration import (
    MIGRATION_MARKER_FILENAME,
    MIGRATION_SCHEMA_VERSION,
    ensure_procs_migrated,
)


def _write_legacy_store(home: Path, records: list[dict[str, Any]]) -> Path:
    legacy_dir = home / "tasks"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    store = legacy_dir / "tasks.jsonl"
    store.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records),
        encoding="utf-8",
    )
    return legacy_dir


def _legacy_record(task_id: str, *, status: str = "success") -> dict[str, Any]:
    return {
        "task_id": task_id,
        "label": f"Legacy {task_id}",
        "kind": "command",
        "status": status,
        "command": ["true"],
        "cwd": "/tmp",
        "project": "sase",
        "session_id": None,
        "session_label": None,
        "origin": "test",
        "cl_name": None,
        "tags": [],
        "pid": None,
        "pgid": None,
        "exit_code": 0 if status == "success" else None,
        "phase": None,
        "message": None,
        "created_at": "2026-07-25T12:00:00Z",
        "started_at": "2026-07-25T12:00:00Z",
        "finished_at": "2026-07-25T12:00:01Z" if status == "success" else None,
        "log_path": f"/home/legacy/.sase/tasks/logs/{task_id}.log",
    }


def test_migration_rewrites_ids_relocates_store_and_logs(
    monkeypatch: Any, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    legacy_dir = _write_legacy_store(
        home, [_legacy_record("finishedtask"), _legacy_record("otherfinish")]
    )
    legacy_logs = legacy_dir / "logs"
    legacy_logs.mkdir()
    (legacy_logs / "finishedtask.log").write_text("hello\n", encoding="utf-8")
    (legacy_logs / "otherfinish.log").write_text("world\n", encoding="utf-8")
    (legacy_dir / ".task-launch-submit.lock").write_text("", encoding="utf-8")
    (legacy_dir / ".epic-launch-submit.lock").write_text("", encoding="utf-8")

    ensure_procs_migrated()

    new_store = home / "procs" / "procs.jsonl"
    assert new_store.is_file()
    lines = [json.loads(line) for line in new_store.read_text().splitlines()]
    assert {row["proc_id"] for row in lines} == {"finishedtask", "otherfinish"}
    for row in lines:
        assert "task_id" not in row
        assert row["log_path"] == str(home / "procs" / "logs" / f"{row['proc_id']}.log")

    assert not (legacy_dir / "tasks.jsonl").exists()
    assert (home / "procs" / "logs" / "finishedtask.log").read_text() == "hello\n"
    assert (home / "procs" / "logs" / "otherfinish.log").read_text() == "world\n"
    assert legacy_logs.is_symlink()
    assert legacy_logs.resolve() == (home / "procs" / "logs").resolve()

    assert (home / "procs" / ".task-launch-submit.lock").exists()
    assert (home / "procs" / ".epic-launch-submit.lock").exists()
    assert not (legacy_dir / ".task-launch-submit.lock").exists()
    assert not (legacy_dir / ".epic-launch-submit.lock").exists()

    marker = json.loads((home / MIGRATION_MARKER_FILENAME).read_text())
    assert marker == {
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "completed": True,
        "migrated": True,
    }

    # Now readable through the ordinary facade at the new location.
    procs = read_procs(path=new_store)
    assert {proc.proc_id for proc in procs} == {"finishedtask", "otherfinish"}


def test_migration_symlinks_legacy_log_dir_for_a_live_writer(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """A still-open legacy log path keeps writing through after migration."""
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    legacy_dir = _write_legacy_store(
        home, [_legacy_record("runningtask", status="running")]
    )
    legacy_logs = legacy_dir / "logs"
    legacy_logs.mkdir()
    legacy_log_path = legacy_logs / "runningtask.log"
    legacy_log_path.write_text("start\n", encoding="utf-8")

    ensure_procs_migrated()

    # A writer that still resolves the pre-migration path (as an
    # already-spawned legacy supervisor would) is transparently redirected.
    fd = os.open(str(legacy_log_path), os.O_CREAT | os.O_WRONLY | os.O_APPEND)
    try:
        os.write(fd, b"more\n")
    finally:
        os.close(fd)

    new_log_path = home / "procs" / "logs" / "runningtask.log"
    assert new_log_path.read_text() == "start\nmore\n"


def test_migration_merges_logs_into_an_existing_canonical_logs_dir(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Legacy logs follow the rows even if ``procs/logs`` already exists."""
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    legacy_dir = _write_legacy_store(home, [_legacy_record("legacylog01")])
    legacy_logs = legacy_dir / "logs"
    legacy_logs.mkdir()
    (legacy_logs / "legacylog01.log").write_text("legacy\n", encoding="utf-8")
    # A partially migrated home already wrote canonical logs before the
    # migration ran, so the destination directory is not free.
    new_logs = home / "procs" / "logs"
    new_logs.mkdir(parents=True)
    (new_logs / "alreadyhere.log").write_text("canonical\n", encoding="utf-8")

    ensure_procs_migrated()

    # The rewritten row points into the canonical logs dir, so its log has to
    # actually be there rather than stranded at the legacy location.
    row = json.loads((home / "procs" / "procs.jsonl").read_text().strip())
    assert row["log_path"] == str(new_logs / "legacylog01.log")
    assert (new_logs / "legacylog01.log").read_text() == "legacy\n"
    assert (new_logs / "alreadyhere.log").read_text() == "canonical\n"
    assert legacy_logs.is_symlink()
    assert legacy_logs.resolve() == new_logs.resolve()


def test_migration_keeps_a_canonical_log_that_collides_with_a_legacy_one(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """A same-named canonical log wins and the legacy copy is not destroyed."""
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    legacy_dir = _write_legacy_store(home, [_legacy_record("collidelog1")])
    legacy_logs = legacy_dir / "logs"
    legacy_logs.mkdir()
    (legacy_logs / "collidelog1.log").write_text("legacy\n", encoding="utf-8")
    new_logs = home / "procs" / "logs"
    new_logs.mkdir(parents=True)
    (new_logs / "collidelog1.log").write_text("canonical\n", encoding="utf-8")

    ensure_procs_migrated()

    assert (new_logs / "collidelog1.log").read_text() == "canonical\n"
    # Nothing is deleted, and the leftover stays reachable rather than being
    # hidden behind a symlink to its canonical namesake.
    assert not legacy_logs.is_symlink()
    assert (legacy_logs / "collidelog1.log").read_text() == "legacy\n"


def test_migration_is_idempotent(monkeypatch: Any, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    _write_legacy_store(home, [_legacy_record("onlyonetask")])

    ensure_procs_migrated()
    new_store = home / "procs" / "procs.jsonl"
    first_run_contents = new_store.read_text()

    # A second call must be a clean no-op: no exception, store unchanged.
    ensure_procs_migrated()
    assert new_store.read_text() == first_run_contents


def test_migration_skips_cleanly_when_no_legacy_store_exists(
    monkeypatch: Any, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))

    ensure_procs_migrated()

    assert not (home / "procs" / "procs.jsonl").exists()
    marker = json.loads((home / MIGRATION_MARKER_FILENAME).read_text())
    assert marker["completed"] is True
    assert marker["migrated"] is False


def test_store_facade_triggers_migration_lazily(
    monkeypatch: Any, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    _write_legacy_store(home, [_legacy_record("lazytask01")])

    # Never call ensure_procs_migrated() directly: an ordinary facade read
    # against the default (new) store path must trigger it on first use.
    procs = read_procs()

    assert {proc.proc_id for proc in procs} == {"lazytask01"}
    assert (home / "procs" / "procs.jsonl").is_file()


def test_migration_does_not_disturb_an_already_migrated_store(
    monkeypatch: Any, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    # A store that already exists at the canonical location (e.g. a fresh
    # install that never had ~/.sase/tasks) must never be touched, even if a
    # ~/.sase/tasks directory happens to exist alongside it. Write it directly
    # rather than through the facade, so no migration has run yet and the
    # marker is still absent when ensure_procs_migrated() is called below.
    new_dir = home / "procs"
    new_dir.mkdir(parents=True)
    canonical_row = {
        "proc_id": "canonicalone",
        "label": "Canonical",
        "kind": "command",
        "status": "success",
        "command": ["true"],
        "cwd": "/tmp",
        "origin": "test",
        "tags": [],
        "created_at": "2026-07-25T12:00:00Z",
        "log_path": str(new_dir / "logs" / "canonicalone.log"),
    }
    new_store = new_dir / "procs.jsonl"
    new_store.write_text(f"{json.dumps(canonical_row)}\n", encoding="utf-8")
    legacy_dir = _write_legacy_store(home, [_legacy_record("shouldbeignored")])

    ensure_procs_migrated()

    assert new_store.read_text() == f"{json.dumps(canonical_row)}\n"
    procs = read_procs(path=new_store)
    assert {proc.proc_id for proc in procs} == {"canonicalone"}
    # The skip path never deletes anything it didn't migrate.
    assert (legacy_dir / "tasks.jsonl").is_file()
    assert get_proc("shouldbeignored", path=new_store) is None
