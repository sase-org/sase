"""Dry-run, apply, resume, status, and verify driver for ``sase migrate``.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.time import local_now
from sase.migration_kit.atomic import atomic_write_text
from sase.migration_kit.catalog import OPERATION_SPECS
from sase.migration_kit.core_contract import bounded_lock, migration_wire_schema_version
from sase.migration_kit.driver_backup import backup_record
from sase.migration_kit.driver_context import (
    generate_run_id,
    operation_context,
    operation_or_error,
    resolve_catalog_root,
)
from sase.migration_kit.driver_manifest import (
    context_from_manifest,
    load_manifest,
    manifest_for,
    manifest_source_digests,
    observed_source_digests_for_replay,
    operation_name_from_manifest,
    single_operation_entry,
)
from sase.migration_kit.driver_outcome import MigrationCommandOutcome
from sase.migration_kit.driver_preflight import (
    ABORT_AFTER_ARCHIVES_ENV_VAR,
    abort_after_archives_from_env,
    append_backed_up_if_needed,
    preflight_manifest,
    refused,
)
from sase.migration_kit.journal import (
    append_record,
    current_resume_plan,
    ensure_run_dir,
    read_records,
)
from sase.migration_kit.operations.base import MigrationInjectedAbort
from sase.migration_kit.paths import (
    run_lock_path,
    run_manifest_path,
    run_receipt_path,
    runs_dir,
)

DEFAULT_LOCK_TIMEOUT_MS = 5_000


def list_operations(
    *,
    root: Path | None = None,
    home: Path | None = None,
) -> MigrationCommandOutcome:
    """Return the fixed operation catalog with per-root applicability."""
    context = operation_context(
        run_id="catalog",
        root=root,
        home=home,
        backup_id=None,
    )
    operations = []
    for spec in OPERATION_SPECS:
        operations.append(
            {
                **spec.to_dict(),
                "applicability": [
                    {
                        "root": root_label,
                        "resolved": str(resolve_catalog_root(root_label, context)),
                        "exists": resolve_catalog_root(root_label, context).exists(),
                    }
                    for root_label in spec.roots
                ],
            }
        )
    return MigrationCommandOutcome(
        True,
        command="list",
        dry_run=True,
        message=f"{len(operations)} migration operation(s)",
        details={"operations": operations},
    )


def plan_operation(
    operation_name: str,
    *,
    root: Path | None = None,
    home: Path | None = None,
    backup_id: str | None = None,
) -> MigrationCommandOutcome:
    """Build and persist a dry-run manifest for one operation."""
    operation = operation_or_error(operation_name)
    if isinstance(operation, MigrationCommandOutcome):
        return operation
    run_id = generate_run_id(operation.spec.name)
    context = operation_context(
        run_id=run_id,
        root=root,
        home=home,
        backup_id=backup_id,
    )
    operation_entry = operation.plan(context)
    backups = (
        [backup_record(backup_id, operation_entry=operation_entry)]
        if backup_id is not None
        else []
    )
    manifest = manifest_for(
        run_id=run_id,
        operation=operation.spec,
        operation_entry=operation_entry,
        context=context,
        backups=backups,
    )
    ensure_run_dir(run_id)
    manifest_path = run_manifest_path(run_id)
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    append_record(
        run_id,
        state="planned",
        operation=operation.spec.name,
        message="manifest planned",
        source_digests=manifest_source_digests(manifest),
    )
    return MigrationCommandOutcome(
        True,
        command="plan",
        dry_run=True,
        message=f"planned {operation.spec.name}",
        run_id=run_id,
        manifest_path=str(manifest_path),
        details={"manifest": manifest},
    )


def run_manifest(
    manifest_path: Path,
    *,
    apply: bool,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
) -> MigrationCommandOutcome:
    """Dry-run or apply a persisted manifest."""
    manifest = load_manifest(manifest_path)
    if isinstance(manifest, MigrationCommandOutcome):
        return manifest
    run_id = str(manifest.get("run_id") or manifest.get("manifest_id"))
    context = context_from_manifest(manifest)
    operation_entry = single_operation_entry(manifest)
    if operation_entry is None:
        return refused(
            command="run",
            dry_run=not apply,
            run_id=run_id,
            message="manifest must contain exactly one operation",
            reason="invalid manifest operation count",
        )
    operation_name = str(operation_entry["operation"])
    operation = operation_or_error(operation_name)
    if isinstance(operation, MigrationCommandOutcome):
        return operation

    records = read_records(run_id)
    if records and records[-1].get("state") == "verified":
        verify_outcome = operation.verify(context, operation_entry)
        if verify_outcome.ok:
            return MigrationCommandOutcome(
                True,
                command="run",
                dry_run=not apply,
                message="migration already verified; no-op",
                run_id=run_id,
                manifest_path=str(manifest_path),
                receipt_path=str(run_receipt_path(run_id))
                if run_receipt_path(run_id).is_file()
                else None,
                details={"verify": verify_outcome.to_dict()},
            )

    observed_digests = observed_source_digests_for_replay(manifest, records)
    resume_plan = current_resume_plan(
        manifest,
        records=records,
        observed_source_digests=observed_digests,
    )
    if resume_plan.get("refused"):
        append_record(
            run_id,
            state="refused",
            operation=operation_name,
            message=str(resume_plan.get("refusal_reason") or "refused"),
            source_digests=observed_digests,
            refusal={"reason": str(resume_plan.get("refusal_reason") or "refused")},
        )
        return MigrationCommandOutcome(
            False,
            command="run",
            dry_run=not apply,
            message="source digest gate refused the manifest",
            run_id=run_id,
            manifest_path=str(manifest_path),
            errors=(str(resume_plan.get("refusal_reason") or "refused"),),
            details={"resume_plan": resume_plan},
        )

    if apply and not operation.spec.apply_supported:
        return refused(
            command="run",
            dry_run=False,
            run_id=run_id,
            message=f"{operation.spec.name} has no apply path",
            reason="operation is dry-run/verify only",
        )

    preflight = preflight_manifest(manifest, operation_entry)
    if not preflight.ok:
        append_record(
            run_id,
            state="refused",
            operation=operation_name,
            message=preflight.message,
            source_digests=observed_digests,
            refusal={
                "reason": preflight.message,
                "detail": "\n".join(preflight.errors),
            },
        )
        return MigrationCommandOutcome(
            False,
            command="run",
            dry_run=not apply,
            message=preflight.message,
            run_id=run_id,
            manifest_path=str(manifest_path),
            errors=preflight.errors,
            details={"preflight": preflight.details},
        )

    if not apply:
        return MigrationCommandOutcome(
            True,
            command="run",
            dry_run=True,
            message="dry run preflight passed; no changes applied",
            run_id=run_id,
            manifest_path=str(manifest_path),
            details={"resume_plan": resume_plan, "preflight": preflight.details},
        )

    context.abort_after_archives = abort_after_archives_from_env()
    with bounded_lock(
        run_lock_path(run_id),
        timeout_ms=lock_timeout_ms,
        operation=f"migration:{operation_name}",
    ):
        try:
            append_backed_up_if_needed(
                run_id, records, operation_name, observed_digests
            )
            append_record(
                run_id,
                state="applying",
                operation=operation_name,
                message="applying operation",
                source_digests=observed_digests,
            )
            apply_outcome = operation.apply(context, operation_entry)
            if not apply_outcome.ok:
                append_record(
                    run_id,
                    state="refused",
                    operation=operation_name,
                    message=apply_outcome.message,
                    source_digests=observed_digests,
                    refusal={
                        "reason": apply_outcome.message,
                        "detail": "\n".join(apply_outcome.errors),
                    },
                )
                return MigrationCommandOutcome(
                    False,
                    command="run",
                    dry_run=False,
                    message=apply_outcome.message,
                    run_id=run_id,
                    manifest_path=str(manifest_path),
                    errors=apply_outcome.errors,
                    details={"apply": apply_outcome.to_dict()},
                )
            append_record(
                run_id,
                state="applied",
                operation=operation_name,
                message=apply_outcome.message,
                source_digests=observed_digests,
            )
            verify_outcome = operation.verify(context, operation_entry)
            if not verify_outcome.ok:
                append_record(
                    run_id,
                    state="failed",
                    operation=operation_name,
                    message=verify_outcome.message,
                    source_digests=observed_digests,
                )
                return MigrationCommandOutcome(
                    False,
                    command="run",
                    dry_run=False,
                    message=verify_outcome.message,
                    run_id=run_id,
                    manifest_path=str(manifest_path),
                    errors=verify_outcome.errors,
                    details={
                        "apply": apply_outcome.to_dict(),
                        "verify": verify_outcome.to_dict(),
                    },
                )
            append_record(
                run_id,
                state="verified",
                operation=operation_name,
                message=verify_outcome.message,
                source_digests=observed_digests,
            )
        except MigrationInjectedAbort:
            raise

    receipt = {
        "schema_version": migration_wire_schema_version(),
        "run_id": run_id,
        "operation": operation_name,
        "completed_at": local_now().isoformat(),
        "apply": apply_outcome.to_dict(),
        "verify": verify_outcome.to_dict(),
        "manifest_path": str(manifest_path),
    }
    receipt_path = run_receipt_path(run_id)
    atomic_write_text(
        receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    return MigrationCommandOutcome(
        True,
        command="run",
        dry_run=False,
        message="migration applied and verified",
        run_id=run_id,
        manifest_path=str(manifest_path),
        receipt_path=str(receipt_path),
        details={"receipt": receipt},
    )


def resume_run(
    run_id: str,
    *,
    apply: bool,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
) -> MigrationCommandOutcome:
    """Continue a run from its journal."""
    manifest_path = run_manifest_path(run_id)
    if not manifest_path.is_file():
        return MigrationCommandOutcome(
            False,
            command="resume",
            dry_run=not apply,
            message=f"no manifest found for run {run_id}",
            run_id=run_id,
            manifest_path=str(manifest_path),
            errors=(f"{manifest_path}: missing",),
        )
    outcome = run_manifest(
        manifest_path,
        apply=apply,
        lock_timeout_ms=lock_timeout_ms,
    )
    return MigrationCommandOutcome(
        outcome.ok,
        command="resume",
        dry_run=outcome.dry_run,
        message=outcome.message,
        run_id=outcome.run_id,
        manifest_path=outcome.manifest_path,
        receipt_path=outcome.receipt_path,
        errors=outcome.errors,
        details=outcome.details,
    )


def status_runs() -> MigrationCommandOutcome:
    """Return every run and its latest journal state."""
    runs = []
    root = runs_dir()
    for path in sorted(item for item in root.iterdir() if item.is_dir()):
        manifest_path = path / "manifest.json"
        manifest = load_manifest(manifest_path) if manifest_path.is_file() else None
        records = read_records(path.name)
        runs.append(
            {
                "run_id": path.name,
                "manifest_path": str(manifest_path)
                if manifest_path.is_file()
                else None,
                "operation": operation_name_from_manifest(manifest)
                if isinstance(manifest, dict)
                else None,
                "state": records[-1]["state"] if records else "missing",
                "resumable": bool(records)
                and str(records[-1]["state"]) in {"planned", "backed_up", "applying"},
                "receipt_path": str(path / "receipt.json")
                if (path / "receipt.json").is_file()
                else None,
            }
        )
    return MigrationCommandOutcome(
        True,
        command="status",
        dry_run=True,
        message=f"{len(runs)} migration run(s)",
        details={"runs": runs},
    )


def verify_run(run_id: str) -> MigrationCommandOutcome:
    """Re-check post-conditions for one run."""
    manifest = load_manifest(run_manifest_path(run_id))
    if isinstance(manifest, MigrationCommandOutcome):
        return manifest
    operation_entry = single_operation_entry(manifest)
    if operation_entry is None:
        return MigrationCommandOutcome(
            False,
            command="verify",
            dry_run=True,
            message="manifest must contain exactly one operation",
            run_id=run_id,
        )
    operation = operation_or_error(str(operation_entry["operation"]))
    if isinstance(operation, MigrationCommandOutcome):
        return operation
    context = context_from_manifest(manifest)
    outcome = operation.verify(context, operation_entry)
    return MigrationCommandOutcome(
        outcome.ok,
        command="verify",
        dry_run=True,
        message=outcome.message,
        run_id=run_id,
        manifest_path=str(run_manifest_path(run_id)),
        receipt_path=str(run_receipt_path(run_id))
        if run_receipt_path(run_id).is_file()
        else None,
        errors=outcome.errors,
        details=outcome.details,
    )


__all__ = [
    "ABORT_AFTER_ARCHIVES_ENV_VAR",
    "DEFAULT_LOCK_TIMEOUT_MS",
    "MigrationCommandOutcome",
    "list_operations",
    "plan_operation",
    "resume_run",
    "run_manifest",
    "status_runs",
    "verify_run",
]
