"""Write-ahead journal, atomic golden application, rollback, and recovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import stat as stat_module
from typing import Any

from tests.ace.tui.visual._visual_capture_paths import (
    atomic_write_bytes,
    atomic_write_text,
    sha256_bytes,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    JOURNAL_APPLIED,
    JOURNAL_APPLYING,
    JOURNAL_CONFLICT,
    JOURNAL_FILENAME,
    JOURNAL_KIND,
    JOURNAL_PLANNED,
    JOURNAL_ROLLED_BACK,
    JOURNAL_SCHEMA_VERSION,
    KIND_CREATED,
    KIND_STALE,
    KIND_UPDATED,
    ChangeRecord,
    MaintenanceError,
    RUNS_DIRNAME,
)


UNFINISHED_STATUSES = frozenset({JOURNAL_PLANNED, JOURNAL_APPLYING})


def journal_path_for(run_dir: Path) -> Path:
    return run_dir / JOURNAL_FILENAME


def find_unfinished_journals(cache_root: Path) -> list[Path]:
    """Return apply journals that did not finish."""
    runs = cache_root / RUNS_DIRNAME
    if not runs.is_dir():
        return []
    found: list[Path] = []
    for run_dir in sorted(runs.iterdir()):
        path = journal_path_for(run_dir)
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(payload, Mapping)
            and payload.get("kind") == JOURNAL_KIND
            and payload.get("status") in UNFINISHED_STATUSES
        ):
            found.append(path)
    return found


def recover_unfinished_journals(
    cache_root: Path,
    repo_root: Path,
    *,
    allow_writes: bool,
) -> tuple[str, ...]:
    """Restore goldens from unfinished journals, or refuse in check mode."""
    journals = find_unfinished_journals(cache_root)
    if not journals:
        return ()
    labels = tuple(str(path) for path in journals)
    if not allow_writes:
        raise MaintenanceError(
            "unfinished screenshot apply journal found; check mode refuses "
            "recovery writes: " + ", ".join(labels)
        )
    recovered: list[str] = []
    for path in journals:
        recover_journal(path, repo_root)
        recovered.append(str(path))
    return tuple(recovered)


def recover_journal(path: Path, repo_root: Path) -> None:
    """Restore baseline bytes when current files match known before/after hashes."""
    payload = _load_journal(path)
    conflicts: list[str] = []
    for entry in payload.get("entries", []):
        if not isinstance(entry, Mapping):
            continue
        conflict = _recover_entry(entry, path.parent, repo_root)
        if conflict is not None:
            conflicts.append(conflict)
    if conflicts:
        payload["status"] = JOURNAL_CONFLICT
        payload["conflicts"] = conflicts
        _write_journal(path, payload)
        raise MaintenanceError(
            "unfinished apply journal has conflicts and cannot be restored: "
            + "; ".join(conflicts)
        )
    payload["status"] = JOURNAL_ROLLED_BACK
    for entry in payload.get("entries", []):
        if isinstance(entry, dict):
            entry["state"] = "rolled_back"
    _write_journal(path, payload)


def plan_journal(
    run_dir: Path,
    changes: Sequence[ChangeRecord],
    *,
    repo_root: Path,
    capture_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    """Copy backups and write a planned journal before any golden mutation."""
    entries: list[dict[str, Any]] = []
    for change in changes:
        if change.kind not in {KIND_CREATED, KIND_UPDATED, KIND_STALE}:
            continue
        entries.append(
            _plan_entry(
                change,
                run_dir=run_dir,
                repo_root=repo_root,
                capture_dir=capture_dir,
            )
        )
    payload: dict[str, Any] = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "kind": JOURNAL_KIND,
        "run_id": run_id,
        "status": JOURNAL_PLANNED,
        "entries": entries,
    }
    _write_journal(journal_path_for(run_dir), payload)
    return payload


def apply_journal(
    run_dir: Path,
    payload: dict[str, Any],
    *,
    repo_root: Path,
    capture_dir: Path,
) -> None:
    """Apply planned journal entries with rollback on handled failures."""
    path = journal_path_for(run_dir)
    payload["status"] = JOURNAL_APPLYING
    _write_journal(path, payload)
    applied: list[dict[str, Any]] = []
    try:
        for entry in payload["entries"]:
            _apply_entry(entry, repo_root=repo_root, capture_dir=capture_dir)
            entry["state"] = "applied"
            applied.append(entry)
            _write_journal(path, payload)
    except BaseException as exc:
        rollback_error: Exception | None = None
        try:
            _rollback_entries(
                reversed(applied),
                repo_root=repo_root,
                run_dir=run_dir,
            )
        except Exception as nested:
            rollback_error = nested
        payload["status"] = JOURNAL_ROLLED_BACK
        for entry in payload["entries"]:
            if entry.get("state") == "applied":
                entry["state"] = "rolled_back"
        _write_journal(path, payload)
        if isinstance(exc, KeyboardInterrupt):
            raise
        message = f"applying screenshot goldens failed: {exc}"
        if rollback_error is not None:
            message += f"; rollback also failed: {rollback_error}"
        raise MaintenanceError(message) from exc
    payload["status"] = JOURNAL_APPLIED
    _write_journal(path, payload)


def apply_changes(
    run_dir: Path,
    changes: Sequence[ChangeRecord],
    *,
    repo_root: Path,
    capture_dir: Path,
    run_id: str,
) -> Path:
    """Write the journal, apply actionable changes, and return the journal path."""
    payload = plan_journal(
        run_dir,
        changes,
        repo_root=repo_root,
        capture_dir=capture_dir,
        run_id=run_id,
    )
    apply_journal(run_dir, payload, repo_root=repo_root, capture_dir=capture_dir)
    return journal_path_for(run_dir)


def _plan_entry(
    change: ChangeRecord,
    *,
    run_dir: Path,
    repo_root: Path,
    capture_dir: Path,
) -> dict[str, Any]:
    action = {
        KIND_CREATED: "create",
        KIND_UPDATED: "update",
        KIND_STALE: "delete",
    }[change.kind]
    backup_relpath = None
    source = repo_root / change.path
    if action in {"update", "delete"} and source.is_file():
        backup_relpath = f"backups/{change.path}"
        atomic_write_bytes(run_dir / backup_relpath, source.read_bytes())
    after_sha = change.candidate_sha256
    if action == "delete":
        after_sha = None
    elif after_sha is None and change.candidate_png_relpath:
        after_sha = sha256_bytes(
            (capture_dir / change.candidate_png_relpath).read_bytes()
        )
    return {
        "path": change.path,
        "action": action,
        "before_sha256": change.baseline_sha256,
        "after_sha256": after_sha,
        "backup_relpath": backup_relpath,
        "candidate_png_relpath": change.candidate_png_relpath,
        "state": "pending",
    }


def _apply_entry(
    entry: Mapping[str, Any],
    *,
    repo_root: Path,
    capture_dir: Path,
) -> None:
    target = repo_root / str(entry["path"])
    action = str(entry["action"])
    if action == "delete":
        if target.is_file() or target.is_symlink():
            target.unlink()
        return
    relpath = entry.get("candidate_png_relpath")
    if not isinstance(relpath, str) or not relpath:
        raise MaintenanceError(f"journal entry missing candidate for {entry['path']}")
    data = (capture_dir / relpath).read_bytes()
    expected = entry.get("after_sha256")
    if isinstance(expected, str) and sha256_bytes(data) != expected:
        raise MaintenanceError(f"candidate changed before apply: {entry['path']}")
    _atomic_replace(target, data, preserve_mode=action == "update")


def _rollback_entries(
    entries: Sequence[Mapping[str, Any]],
    *,
    repo_root: Path,
    run_dir: Path,
) -> None:
    for entry in entries:
        _restore_entry(entry, run_dir=run_dir, repo_root=repo_root, require_known=False)


def _recover_entry(
    entry: Mapping[str, Any],
    run_dir: Path,
    repo_root: Path,
) -> str | None:
    return _restore_entry(
        entry, run_dir=run_dir, repo_root=repo_root, require_known=True
    )


def _restore_entry(
    entry: Mapping[str, Any],
    *,
    run_dir: Path,
    repo_root: Path,
    require_known: bool,
) -> str | None:
    relative = str(entry["path"])
    target = repo_root / relative
    action = str(entry["action"])
    before = entry.get("before_sha256")
    after = entry.get("after_sha256")
    current = _current_sha(target)
    if current == before or (before is None and current is None):
        return None
    known_after = current == after and after is not None
    missing_created = action == "create" and current is None
    if known_after or (not require_known and current is not None):
        if action == "create":
            if target.is_file() or target.is_symlink():
                target.unlink()
            return None
        backup = entry.get("backup_relpath")
        if not isinstance(backup, str) or not backup:
            return f"{relative}: missing backup"
        backup_path = run_dir / backup
        if not backup_path.is_file():
            return f"{relative}: backup file missing"
        _atomic_replace(target, backup_path.read_bytes(), preserve_mode=False)
        return None
    if missing_created:
        return None
    if require_known:
        return (
            f"{relative}: current hash {current!r} matches neither "
            f"before {before!r} nor after {after!r}"
        )
    backup = entry.get("backup_relpath")
    if isinstance(backup, str) and backup and (run_dir / backup).is_file():
        _atomic_replace(target, (run_dir / backup).read_bytes(), preserve_mode=False)
        return None
    if action == "create" and (target.is_file() or target.is_symlink()):
        target.unlink()
        return None
    return None


def _atomic_replace(path: Path, data: bytes, *, preserve_mode: bool) -> None:
    mode = None
    if preserve_mode and path.exists():
        mode = stat_module.S_IMODE(path.stat().st_mode)
    atomic_write_bytes(path, data)
    if mode is not None:
        os.chmod(path, mode)


def _current_sha(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    return sha256_bytes(path.read_bytes())


def _load_journal(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise MaintenanceError(f"apply journal is not an object: {path}")
    return raw


def _write_journal(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )
