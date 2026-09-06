"""Read-only code-swap lock residue classifier.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import os
from pathlib import Path
from typing import Any

from sase.migration_kit.catalog import get_operation_spec
from sase.migration_kit.operations.base import OperationContext, OperationOutcome
from sase.migration_kit.operations.util import digest_path, fingerprint_json

_CURRENT_CODE_SWAP_LOCK = "code-swap-v2.lock"
_LOCK_FILENAMES = ("code-swap.lock", "code-swap-v2.lock")


class LockResidueOperation:
    """Classify lock files without mutating them."""

    spec = get_operation_spec("lock-residue")

    def plan(self, context: OperationContext) -> dict[str, Any]:
        locks_dir = context.sase_home / "locks"
        classifications = [
            _classify_lock(locks_dir / filename) for filename in _LOCK_FILENAMES
        ]
        source_digests = {
            item["path"]: digest_path(Path(item["path"])) for item in classifications
        }
        return {
            "schema_version": 1,
            "operation": self.spec.name,
            "roots": [str(locks_dir)],
            "source_paths": sorted(source_digests),
            "destinations": [],
            "source_digests": source_digests,
            "schema_versions": {"migration": 1},
            "record_counts": {"locks": len(classifications)},
            "semantic_fingerprints": {
                "lock-residue": fingerprint_json(classifications)
            },
            "detected_conflicts": [],
            "estimated_space_bytes": 0,
            "backup_required": self.spec.backup_required,
            "backup_ids": [],
            "preconditions": list(self.spec.preconditions),
            "verification_query": {"classifications": classifications},
            "rollback_unit": self.spec.rollback_unit,
            "intended_action": "dry_run",
            "x_actions": [],
            "x_classifications": classifications,
        }

    def apply(
        self, context: OperationContext, operation_entry: dict[str, Any]
    ) -> OperationOutcome:
        return OperationOutcome(
            False,
            "lock-residue is read-only; run verify to record classification",
            errors=("lock-residue has no apply path",),
        )

    def verify(
        self, context: OperationContext, operation_entry: dict[str, Any]
    ) -> OperationOutcome:
        current = self.plan(context)["x_classifications"]
        return OperationOutcome(
            True,
            "lock residue classification verified",
            details={"classifications": current},
        )


def _classify_lock(path: Path) -> dict[str, Any]:
    exists = path.exists() or path.is_symlink()
    stat_result = path.lstat() if exists else None
    return {
        "path": str(path),
        "filename": path.name,
        "exists": exists,
        "held": _lock_is_held(path) if exists and not path.is_symlink() else False,
        "mtime": _mtime_iso(stat_result.st_mtime) if stat_result else None,
        "current_code_writes": path.name == _CURRENT_CODE_SWAP_LOCK,
        "writer_code_path": "src/sase/dev_update/code_swap_lock.py"
        if path.name == _CURRENT_CODE_SWAP_LOCK
        else None,
        "decision": "refuse_archive_current_writer"
        if path.name == _CURRENT_CODE_SWAP_LOCK
        else "classify_only",
    }


def _lock_is_held(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
    finally:
        os.close(fd)


def _mtime_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


__all__ = ["LockResidueOperation"]
