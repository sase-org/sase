"""Proc log-lock orphan owner step for ``sase disk reap``."""

from __future__ import annotations

import fcntl
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.config.core import (
    get_proc_log_lock_orphan_horizon_seconds,
    get_proc_log_lock_orphan_max_removals,
)
from sase.core.disk_footprint_models import DiskReapStep
from sase.procs.logs import proc_logs_dir
from sase.procs.store import read_proc_snapshot

#: Owner name shared by the inventory row, the reap step, and pressure notices.
PROC_LOG_LOCK_SWEEP_OWNER = "proc_log_lock_sweep"


@dataclass(frozen=True)
class _ProcLogLockSweepResult:
    """Outcome of sweeping orphaned proc log lock files."""

    scanned: int = 0
    selected: int = 0
    removed: int = 0
    skipped: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)
    reclaimable_bytes: int = 0
    reclaimed_bytes: int = 0
    capped: bool = False
    paths: tuple[str, ...] = field(default_factory=tuple)


def _proc_id_for_lock(lock_name: str, log_suffix: str = ".log") -> str | None:
    """Return the proc id for a lock filename, or ``None`` when malformed."""
    if not lock_name.startswith(".") or not lock_name.endswith(".lock"):
        return None
    inner = lock_name[1 : -len(".lock")]
    if not inner.endswith(log_suffix) or len(inner) <= len(log_suffix):
        return None
    proc_id = inner[: -len(log_suffix)]
    if (
        not proc_id
        or proc_id in {".", ".."}
        or "/" in proc_id
        or "\\" in proc_id
        or "\x00" in proc_id
    ):
        return None
    return proc_id


def _sweep_orphan_proc_log_locks(
    *,
    apply: bool,
    horizon_seconds: float | None = None,
    max_removals: int | None = None,
    now: float | None = None,
    live_proc_ids: set[str] | None = None,
    logs_dir: Path | None = None,
) -> _ProcLogLockSweepResult:
    """Remove ``.<id>.log.lock`` files whose log siblings and proc row are gone.

    A lock is eligible only when no ``<id>.log`` or ``<id>.log.1`` sibling
    exists, no proc row references the id, and the lock is older than the
    horizon. Removal takes the lock non-blocking and skips the file on
    contention; the sibling absence is re-checked under the lock. Only direct
    children of the proc log root are considered and symlinks are never
    followed. At most *max_removals* locks go in one pass, oldest first.
    """
    horizon = (
        get_proc_log_lock_orphan_horizon_seconds()
        if horizon_seconds is None
        else horizon_seconds
    )
    budget = (
        get_proc_log_lock_orphan_max_removals()
        if max_removals is None
        else max_removals
    )
    moment = time.time() if now is None else now
    root = proc_logs_dir() if logs_dir is None else logs_dir
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        return _ProcLogLockSweepResult(errors=(f"proc log dir listing failed: {exc}",))
    live = live_proc_ids if live_proc_ids is not None else set()
    candidates: list[tuple[float, int, str, Path]] = []
    skipped = 0
    errors: list[str] = []
    for entry in entries:
        proc_id = _proc_id_for_lock(entry.name)
        if proc_id is None:
            continue
        try:
            if entry.is_symlink() or not entry.is_file():
                skipped += 1
                continue
            stat = entry.stat()
        except OSError:
            skipped += 1
            continue
        current = root / f"{proc_id}.log"
        rotated = root / f"{proc_id}.log.1"
        if current.exists() or rotated.exists():
            skipped += 1
            continue
        if proc_id in live:
            skipped += 1
            continue
        if moment - stat.st_mtime < horizon:
            skipped += 1
            continue
        candidates.append((stat.st_mtime, stat.st_size, proc_id, entry))
    candidates.sort(key=lambda item: (item[0], item[2]))
    scanned = len(candidates) + skipped
    selected = candidates[: max(0, budget)]
    capped = len(candidates) > len(selected)
    skipped += len(candidates) - len(selected)
    reclaimable = sum(size for _, size, _, _ in selected)
    removed = 0
    reclaimed = 0
    swept: list[str] = []
    if apply:
        for _, size, proc_id, entry in selected:
            outcome = _remove_lock_nonblocking(root, proc_id, entry)
            if outcome == "removed":
                removed += 1
                reclaimed += size
                swept.append(str(entry))
            elif outcome == "skipped":
                skipped += 1
            else:
                errors.append(f"{entry.name}: {outcome}")
    else:
        swept = [str(entry) for _, _, _, entry in selected]
    return _ProcLogLockSweepResult(
        scanned=scanned,
        selected=len(selected),
        removed=removed,
        skipped=skipped,
        errors=tuple(errors),
        reclaimable_bytes=reclaimable,
        reclaimed_bytes=reclaimed,
        capped=capped,
        paths=tuple(swept),
    )


def _remove_lock_nonblocking(root: Path, proc_id: str, entry: Path) -> str:
    """Unlink one orphan lock under a non-blocking flock; never create it."""
    try:
        fd = os.open(entry, os.O_RDWR)
    except FileNotFoundError:
        return "skipped"
    except OSError as exc:
        return f"open failed: {exc}"
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "skipped"
        except OSError as exc:
            return f"lock failed: {exc}"
        try:
            # A sibling log may have appeared after the scan; keep a live lock.
            if (root / f"{proc_id}.log").exists() or (
                root / f"{proc_id}.log.1"
            ).exists():
                return "skipped"
            entry.unlink()
        except FileNotFoundError:
            return "skipped"
        except OSError as exc:
            return f"unlink failed: {exc}"
        return "removed"
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def proc_log_lock_reap_step(*, apply: bool) -> DiskReapStep:
    """Preview or apply the orphaned proc log-lock sweep."""
    try:
        live_proc_ids = {proc.proc_id for proc in read_proc_snapshot().procs}
    except Exception as exc:  # noqa: BLE001 - one owner must not crash the group.
        return DiskReapStep(
            owner=PROC_LOG_LOCK_SWEEP_OWNER,
            mode="blocked",
            summary=f"could not read proc store: {exc}",
            command=("sase", "disk", "reap", "--apply"),
            exit_code=1,
        )
    try:
        result = _sweep_orphan_proc_log_locks(apply=apply, live_proc_ids=live_proc_ids)
    except Exception as exc:  # noqa: BLE001 - one owner must not crash the group.
        return DiskReapStep(
            owner=PROC_LOG_LOCK_SWEEP_OWNER,
            mode="blocked",
            summary=f"could not sweep proc log locks: {exc}",
            command=("sase", "disk", "reap", "--apply"),
            exit_code=1,
        )
    if not apply:
        capped = " (removal budget reached)" if result.capped else ""
        return DiskReapStep(
            owner=PROC_LOG_LOCK_SWEEP_OWNER,
            mode="dry_run",
            summary=(
                f"would remove {result.selected} orphan proc log lock(s)"
                f"{capped}; scanned={result.scanned}, "
                f"reclaimable={result.reclaimable_bytes}"
            ),
            reclaimed_bytes=result.reclaimable_bytes,
            exit_code=1 if result.errors else None,
            owner_error="; ".join(result.errors) if result.errors else None,
            byte_accounting_complete=not result.errors,
            capped=result.capped,
            details=_result_details(result, phase="orphan_lock_preview"),
        )
    capped = " (removal budget reached)" if result.capped else ""
    summary = (
        f"removed {result.removed} orphan proc log lock(s){capped}; "
        f"scanned={result.scanned}, reclaimed={result.reclaimed_bytes}"
    )
    if result.errors:
        summary += f"; errors={len(result.errors)}"
    return DiskReapStep(
        owner=PROC_LOG_LOCK_SWEEP_OWNER,
        mode="apply",
        summary=summary,
        reclaimed_bytes=result.reclaimed_bytes,
        changed=bool(result.removed),
        exit_code=1 if result.errors else None,
        owner_error="; ".join(result.errors) if result.errors else None,
        byte_accounting_complete=not result.errors,
        capped=result.capped,
        details=_result_details(result, phase="orphan_lock_apply"),
    )


def _result_details(result: _ProcLogLockSweepResult, *, phase: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "apply": phase.endswith("apply"),
        "scanned": result.scanned,
        "selected": result.selected,
        "removed": result.removed,
        "skipped": result.skipped,
        "errors": len(result.errors),
        "error_details": list(result.errors),
        "reclaimable_bytes": result.reclaimable_bytes,
        "reclaimed_bytes": result.reclaimed_bytes,
        "capped": result.capped,
        "paths": list(result.paths),
    }


__all__ = [
    "PROC_LOG_LOCK_SWEEP_OWNER",
    "proc_log_lock_reap_step",
]
