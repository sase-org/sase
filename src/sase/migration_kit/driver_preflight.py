"""Preflight validation and journal bookkeeping for the migration driver.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

import os
from typing import Any

from sase.migration_kit.driver_outcome import MigrationCommandOutcome
from sase.migration_kit.journal import append_record
from sase.migration_kit.operations.base import OperationOutcome

ABORT_AFTER_ARCHIVES_ENV_VAR = "SASE_MIGRATION_KIT_ABORT_AFTER_ARCHIVES"


def preflight_manifest(
    manifest: dict[str, Any],
    operation_entry: dict[str, Any],
) -> OperationOutcome:
    conflicts = list(manifest.get("detected_conflicts", [])) + list(
        operation_entry.get("detected_conflicts", [])
    )
    if conflicts:
        return OperationOutcome(
            False,
            "manifest contains detected conflicts",
            errors=tuple(
                f"{conflict.get('kind')}: {conflict.get('path')}"
                for conflict in conflicts
                if isinstance(conflict, dict)
            ),
            details={"conflicts": conflicts},
        )
    if operation_entry.get("backup_required"):
        backups = manifest.get("backups")
        if not isinstance(backups, list) or not backups:
            return OperationOutcome(
                False,
                "verified backup is required before apply",
                errors=("manifest has no backup record",),
            )
        unverified = [
            backup.get("backup_id", "<unknown>")
            for backup in backups
            if isinstance(backup, dict) and not backup.get("verified")
        ]
        if unverified:
            return OperationOutcome(
                False,
                "verified backup is required before apply",
                errors=tuple(
                    f"backup not verified: {backup_id}" for backup_id in unverified
                ),
            )
    return OperationOutcome(True, "preflight passed")


def append_backed_up_if_needed(
    run_id: str,
    records: list[dict[str, Any]],
    operation_name: str,
    observed_digests: dict[str, str],
) -> None:
    states = {str(record.get("state")) for record in records}
    if "backed_up" in states:
        return
    append_record(
        run_id,
        state="backed_up",
        operation=operation_name,
        message="verified backup gate passed",
        source_digests=observed_digests,
    )


def refused(
    *,
    command: str,
    dry_run: bool,
    run_id: str,
    message: str,
    reason: str,
) -> MigrationCommandOutcome:
    append_record(
        run_id,
        state="refused",
        message=message,
        refusal={"reason": reason},
    )
    return MigrationCommandOutcome(
        False,
        command=command,
        dry_run=dry_run,
        message=message,
        run_id=run_id,
        errors=(reason,),
    )


def abort_after_archives_from_env() -> int | None:
    raw = os.environ.get(ABORT_AFTER_ARCHIVES_ENV_VAR)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None
