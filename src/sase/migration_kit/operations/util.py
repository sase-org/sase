"""Shared helpers for temporary migration operation implementations.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
import os
from pathlib import Path
from typing import Any

from sase.migration_kit.atomic import (
    MigrationAtomicError,
    copy_path_atomic,
    remove_path,
)
from sase.migration_kit.core_contract import fingerprint, tree_digest
from sase.migration_kit.operations.base import OperationContext, OperationOutcome
from sase.migration_kit.paths import operation_archive_dir


def digest_path(path: Path) -> str:
    """Return a structural digest for *path*, or ``absent`` when missing."""
    if not (path.exists() or path.is_symlink()):
        return "absent"
    return str(tree_digest(path)["digest"])


def fingerprint_json(value: Any) -> str:
    """Return the shared semantic fingerprint for JSON-like *value*."""
    return fingerprint(value)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL object stream from *path*."""
    records: list[dict[str, Any]] = []
    if not path.is_file():
        return records
    for line_number, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        records.append(value)
    return records


def find_symlink_escapes(root: Path, candidate: Path) -> tuple[str, ...]:
    """Return symlinks under *candidate* that resolve outside *root*."""
    if not (candidate.exists() or candidate.is_symlink()):
        return ()

    root_resolved = root.resolve(strict=False)
    to_scan = [candidate]
    if candidate.is_dir() and not candidate.is_symlink():
        to_scan.extend(candidate.rglob("*"))

    escapes: list[str] = []
    for path in to_scan:
        if not path.is_symlink():
            continue
        raw_target = Path(os.readlink(path))
        target = raw_target if raw_target.is_absolute() else path.parent / raw_target
        resolved_target = target.resolve(strict=False)
        if not is_relative_to(resolved_target, root_resolved):
            escapes.append(f"{path}: {os.readlink(path)}")
    return tuple(sorted(escapes))


def is_relative_to(path: Path, root: Path) -> bool:
    """Return whether *path* is equal to or below *root*."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def live_references(
    *,
    sase_home: Path,
    needles: Iterable[str],
    scan_roots: Iterable[Path] | None = None,
) -> tuple[str, ...]:
    """Return live JSON/text files under SASE state that mention any needle."""
    haystack_roots = tuple(
        scan_roots
        if scan_roots is not None
        else (
            sase_home / "notifications",
            sase_home / "pending_actions",
            sase_home / "gates",
            sase_home / "gate_shells",
            sase_home / "procs",
        )
    )
    needle_values = tuple(value for value in needles if value)
    if not needle_values:
        return ()

    matches: list[str] = []
    for root in haystack_roots:
        paths: tuple[Path, ...]
        if root.is_file():
            paths = (root,)
        elif root.is_dir():
            paths = tuple(path for path in root.rglob("*") if path.is_file())
        else:
            continue
        for path in paths:
            try:
                text = path.read_text("utf-8", errors="ignore")
            except OSError:
                continue
            if any(needle in text for needle in needle_values):
                matches.append(str(path))
    return tuple(sorted(set(matches)))


def archive_remove_actions(
    *,
    context: OperationContext,
    operation: str,
    operation_entry: Mapping[str, Any],
) -> OperationOutcome:
    """Archive then remove every ``archive_remove`` action in *operation_entry*."""
    actions = [
        action
        for action in operation_entry.get("x_actions", [])
        if isinstance(action, dict) and action.get("kind") == "archive_remove"
    ]
    if not actions:
        return OperationOutcome(True, "no residue required archiving")

    backup_id = context.backup_id or _entry_backup_id(operation_entry)
    if not backup_id:
        return OperationOutcome(
            False,
            "verified backup is required",
            errors=("operation has no backup id",),
        )

    archived: list[dict[str, str]] = []
    for action in actions:
        action_id = str(action["action_id"])
        source = Path(str(action["source"]))
        archive_path = operation_archive_dir(
            backup_id,
            run_id=context.run_id,
            operation=operation,
            action_id=action_id,
        )
        expected_digest = str(action["source_digest"])
        if not (source.exists() or source.is_symlink()):
            if _archive_digest(archive_path) == expected_digest:
                archived.append(
                    {
                        "action_id": action_id,
                        "source": str(source),
                        "archive": str(archive_path),
                        "mode": "already-archived",
                    }
                )
                continue
            return OperationOutcome(
                False,
                "source disappeared before archive verification",
                errors=(f"{source}: missing and archive digest does not match",),
            )

        if archive_path.exists() or archive_path.is_symlink():
            if _archive_digest(archive_path) != expected_digest:
                return OperationOutcome(
                    False,
                    "archive destination conflict",
                    errors=(f"{archive_path}: existing archive differs",),
                )
        else:
            actual_digest = copy_path_atomic(source, archive_path)
            if actual_digest != expected_digest:
                raise MigrationAtomicError(
                    f"{source}: copied digest {actual_digest} did not match "
                    f"planned digest {expected_digest}"
                )
            context.abort_point_after_archive()

        remove_path(source)
        archived.append(
            {
                "action_id": action_id,
                "source": str(source),
                "archive": str(archive_path),
                "mode": "archived-and-removed",
            }
        )

    return OperationOutcome(
        True,
        f"archived {len(archived)} residue item(s)",
        details={"archived": archived},
    )


def _entry_backup_id(operation_entry: Mapping[str, Any]) -> str | None:
    backup_ids = operation_entry.get("backup_ids")
    if isinstance(backup_ids, list) and backup_ids:
        return str(backup_ids[0])
    return None


def _archive_digest(path: Path) -> str | None:
    if not (path.exists() or path.is_symlink()):
        return None
    return digest_path(path)


__all__ = [
    "archive_remove_actions",
    "digest_path",
    "find_symlink_escapes",
    "fingerprint_json",
    "is_relative_to",
    "live_references",
    "read_jsonl",
]
