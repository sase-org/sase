"""One-shot on-disk migration from ``~/.sase/tasks`` to ``~/.sase/procs``.

Rewrites legacy ``task_id`` rows to canonical ``proc_id`` rows and relocates
the JSONL store and combined logs. A proc still running under an
already-spawned legacy supervisor may keep appending to its old log path
after migration runs; rather than move that file out from under the live
writer, migration replaces the legacy ``logs/`` directory with a symlink to
the new one, so an in-flight append-by-path write is transparently
redirected to the relocated file instead of silently recreating an empty one
at the old location.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home, sase_subdir
from sase.logs._bounded import log_file_lock

from .paths import PROC_LOGS_SUBDIR, PROC_STORE_FILENAME, procs_dir

MIGRATION_SCHEMA_VERSION = 1
MIGRATION_MARKER_FILENAME = "procs_migration.json"

_LEGACY_SUBDIR = "tasks"
_LEGACY_STORE_FILENAME = "tasks.jsonl"
_LEGACY_LOCK_FILENAMES = (".task-launch-submit.lock", ".epic-launch-submit.lock")

_logger = logging.getLogger(__name__)


def ensure_procs_migrated() -> None:
    """Run the legacy task-store migration once, guarded against races."""
    marker_path = _migration_marker_path()
    if _marker_is_complete(marker_path):
        return
    with log_file_lock(marker_path):
        if _marker_is_complete(marker_path):
            return
        _migrate_legacy_store(marker_path)


def _migration_marker_path() -> Path:
    return sase_home() / MIGRATION_MARKER_FILENAME


def _marker_is_complete(path: Path) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(data, dict)
        and data.get("schema_version") == MIGRATION_SCHEMA_VERSION
        and data.get("completed") is True
    )


def _migrate_legacy_store(marker_path: Path) -> None:
    legacy_dir = sase_subdir(_LEGACY_SUBDIR)
    legacy_store = legacy_dir / _LEGACY_STORE_FILENAME
    new_dir = procs_dir()
    new_store = new_dir / PROC_STORE_FILENAME

    if not legacy_dir.is_dir() or not legacy_store.is_file() or new_store.exists():
        _write_marker(marker_path, migrated=False)
        return

    try:
        _perform_migration(legacy_dir, legacy_store, new_dir, new_store)
    except Exception:
        # Nothing destructive has happened to the legacy directory yet (the
        # store write is the last step); log and let the next lazy call
        # retry from scratch instead of marking migration complete.
        _logger.exception("proc store migration from %s failed", legacy_dir)
        return

    _write_marker(marker_path, migrated=True)


def _perform_migration(
    legacy_dir: Path, legacy_store: Path, new_dir: Path, new_store: Path
) -> None:
    new_dir.mkdir(parents=True, exist_ok=True)

    _relocate_legacy_logs(legacy_dir / PROC_LOGS_SUBDIR, new_dir / PROC_LOGS_SUBDIR)

    for lock_name in _LEGACY_LOCK_FILENAMES:
        legacy_lock = legacy_dir / lock_name
        new_lock = new_dir / lock_name
        if legacy_lock.exists() and not new_lock.exists():
            shutil.move(str(legacy_lock), str(new_lock))

    records = [
        _migrate_record(record, new_dir)
        for record in _read_legacy_records(legacy_store)
    ]
    _write_new_store(new_store, records)

    # Only remove the legacy source once the rewritten store is durably in
    # place, so a crash before this point leaves data for a clean retry.
    legacy_store.unlink()


def _relocate_legacy_logs(legacy_logs_dir: Path, new_logs_dir: Path) -> None:
    """Move the legacy logs under the canonical dir, then symlink the old one.

    Every migrated row's ``log_path`` is rewritten into ``new_logs_dir``, so
    the legacy files have to follow even when that directory already exists —
    a partially migrated home that wrote canonical procs before this ran.
    Merging entry by entry keeps an already-canonical log (the file live
    writers hold open) as the winner instead of overwriting it.
    """
    if not legacy_logs_dir.is_dir() or legacy_logs_dir.is_symlink():
        return

    if new_logs_dir.exists():
        for entry in legacy_logs_dir.iterdir():
            destination = new_logs_dir / entry.name
            if not destination.exists():
                shutil.move(str(entry), str(destination))
        leftovers = list(legacy_logs_dir.iterdir())
        if leftovers:
            # Symlinking now would hide these behind their canonical
            # namesakes, so leave the real directory reachable instead.
            _logger.warning(
                "left %d legacy proc log(s) in %s: %s already holds that name",
                len(leftovers),
                legacy_logs_dir,
                new_logs_dir,
            )
            return
        legacy_logs_dir.rmdir()
    else:
        shutil.move(str(legacy_logs_dir), str(new_logs_dir))

    os.symlink(new_logs_dir, legacy_logs_dir)


def _read_legacy_records(legacy_store: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in legacy_store.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def _migrate_record(record: dict[str, Any], new_dir: Path) -> dict[str, Any]:
    updated = dict(record)
    legacy_id = updated.pop("task_id", None)
    if legacy_id is not None:
        updated.setdefault("proc_id", legacy_id)
    proc_id = updated.get("proc_id")
    if isinstance(proc_id, str) and proc_id:
        updated["log_path"] = str(new_dir / PROC_LOGS_SUBDIR / f"{proc_id}.log")
    return updated


def _write_new_store(new_store: Path, records: list[dict[str, Any]]) -> None:
    lines = "".join(f"{json.dumps(record, sort_keys=True)}\n" for record in records)
    _atomic_write(new_store, lines)


def _write_marker(path: Path, *, migrated: bool) -> None:
    payload = {
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "completed": True,
        "migrated": migrated,
    }
    _atomic_write(path, json.dumps(payload, indent=2) + "\n")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=f".{os.getpid()}.tmp",
        dir=path.parent,
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


__all__ = [
    "MIGRATION_MARKER_FILENAME",
    "MIGRATION_SCHEMA_VERSION",
    "ensure_procs_migrated",
]
