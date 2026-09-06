"""Dry-run, apply, resume, status, and verify driver for ``sase migrate``.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import platform
import secrets
from typing import Any

from sase.core.paths import sase_home
from sase.core.time import local_now
from sase.migration_kit.atomic import atomic_write_text
from sase.migration_kit.catalog import OPERATION_SPECS, OperationSpec
from sase.migration_kit.core_contract import (
    bounded_lock,
    migration_wire_schema_version,
    normalize_manifest,
)
from sase.migration_kit.journal import (
    append_record,
    current_resume_plan,
    ensure_run_dir,
    read_records,
)
from sase.migration_kit.hashing import sha256_file
from sase.migration_kit.manifest import BackupManifest
from sase.migration_kit.operations import get_operation
from sase.migration_kit.operations.base import (
    MigrationInjectedAbort,
    OperationContext,
    OperationOutcome,
)
from sase.migration_kit.operations.util import digest_path
from sase.migration_kit.paths import (
    backup_dir,
    backup_payload_dir,
    run_dir,
    run_lock_path,
    run_manifest_path,
    run_receipt_path,
    runs_dir,
)

DEFAULT_LOCK_TIMEOUT_MS = 5_000
ABORT_AFTER_ARCHIVES_ENV_VAR = "SASE_MIGRATION_KIT_ABORT_AFTER_ARCHIVES"


@dataclass(frozen=True, slots=True)
class MigrationCommandOutcome:
    """Machine-readable result returned by every driver command."""

    ok: bool
    command: str
    dry_run: bool
    message: str
    run_id: str | None = None
    manifest_path: str | None = None
    receipt_path: str | None = None
    errors: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "command": self.command,
            "dry_run": self.dry_run,
            "message": self.message,
            "run_id": self.run_id,
            "manifest_path": self.manifest_path,
            "receipt_path": self.receipt_path,
            "errors": list(self.errors),
            "details": self.details,
        }


def list_operations(
    *,
    root: Path | None = None,
    home: Path | None = None,
) -> MigrationCommandOutcome:
    """Return the fixed operation catalog with per-root applicability."""
    context = _operation_context(
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
                        "resolved": str(_resolve_catalog_root(root_label, context)),
                        "exists": _resolve_catalog_root(root_label, context).exists(),
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
    operation = _operation_or_error(operation_name)
    if isinstance(operation, MigrationCommandOutcome):
        return operation
    run_id = _generate_run_id(operation.spec.name)
    context = _operation_context(
        run_id=run_id,
        root=root,
        home=home,
        backup_id=backup_id,
    )
    operation_entry = operation.plan(context)
    backups = (
        [_backup_record(backup_id, operation_entry=operation_entry)]
        if backup_id is not None
        else []
    )
    manifest = _manifest_for(
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
        source_digests=_manifest_source_digests(manifest),
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
    manifest = _load_manifest(manifest_path)
    if isinstance(manifest, MigrationCommandOutcome):
        return manifest
    run_id = str(manifest.get("run_id") or manifest.get("manifest_id"))
    context = _context_from_manifest(manifest)
    operation_entry = _single_operation_entry(manifest)
    if operation_entry is None:
        return _refused(
            command="run",
            dry_run=not apply,
            run_id=run_id,
            message="manifest must contain exactly one operation",
            reason="invalid manifest operation count",
        )
    operation_name = str(operation_entry["operation"])
    operation = _operation_or_error(operation_name)
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

    observed_digests = _observed_source_digests_for_replay(manifest, records)
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
        return _refused(
            command="run",
            dry_run=False,
            run_id=run_id,
            message=f"{operation.spec.name} has no apply path",
            reason="operation is dry-run/verify only",
        )

    preflight = _preflight_manifest(manifest, operation_entry)
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

    context.abort_after_archives = _abort_after_archives_from_env()
    with bounded_lock(
        run_lock_path(run_id),
        timeout_ms=lock_timeout_ms,
        operation=f"migration:{operation_name}",
    ):
        try:
            _append_backed_up_if_needed(
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
        manifest = _load_manifest(manifest_path) if manifest_path.is_file() else None
        records = read_records(path.name)
        runs.append(
            {
                "run_id": path.name,
                "manifest_path": str(manifest_path)
                if manifest_path.is_file()
                else None,
                "operation": _operation_name_from_manifest(manifest)
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
    manifest = _load_manifest(run_manifest_path(run_id))
    if isinstance(manifest, MigrationCommandOutcome):
        return manifest
    operation_entry = _single_operation_entry(manifest)
    if operation_entry is None:
        return MigrationCommandOutcome(
            False,
            command="verify",
            dry_run=True,
            message="manifest must contain exactly one operation",
            run_id=run_id,
        )
    operation = _operation_or_error(str(operation_entry["operation"]))
    if isinstance(operation, MigrationCommandOutcome):
        return operation
    context = _context_from_manifest(manifest)
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


def _operation_or_error(operation_name: str) -> Any:
    try:
        return get_operation(operation_name)
    except KeyError:
        names = ", ".join(spec.name for spec in OPERATION_SPECS)
        return MigrationCommandOutcome(
            False,
            command="operation",
            dry_run=True,
            message=f"unknown migration operation: {operation_name}",
            errors=(f"known operations: {names}",),
        )


def _generate_run_id(operation_name: str) -> str:
    safe_operation = operation_name.replace("-", "_")
    timestamp = local_now().strftime("%Y%m%dT%H%M%S")
    return f"{platform.node() or 'host'}-{safe_operation}-{timestamp}-{secrets.token_hex(3)}"


def _operation_context(
    *,
    run_id: str,
    root: Path | None,
    home: Path | None,
    backup_id: str | None,
) -> OperationContext:
    resolved_sase_home = (root or sase_home()).expanduser().resolve(strict=False)
    resolved_home = (
        home.expanduser().resolve(strict=False)
        if home is not None
        else resolved_sase_home.parent
    )
    return OperationContext(
        run_id=run_id,
        sase_home=resolved_sase_home,
        home=resolved_home,
        backup_id=backup_id,
    )


def _resolve_catalog_root(root_label: str, context: OperationContext) -> Path:
    if root_label.startswith("~/.sase/"):
        return context.sase_home / root_label.removeprefix("~/.sase/")
    if root_label == "~/.sase":
        return context.sase_home
    if root_label.startswith("~/"):
        return context.home / root_label.removeprefix("~/")
    return Path(root_label).expanduser()


def _manifest_for(
    *,
    run_id: str,
    operation: OperationSpec,
    operation_entry: dict[str, Any],
    context: OperationContext,
    backups: list[dict[str, Any]],
) -> dict[str, Any]:
    source_digests = dict(operation_entry.get("source_digests", {}))
    manifest = {
        "schema_version": migration_wire_schema_version(),
        "manifest_id": run_id,
        "run_id": run_id,
        "created_at": local_now().isoformat(),
        "host_identity": _host_identity(),
        "kit_revision": _git_revision(Path.cwd()),
        "root_revisions": {str(context.sase_home): digest_path(context.sase_home)},
        "repo_revisions": _repo_revisions(),
        "operations": [operation_entry],
        "backups": backups,
        "source_paths": sorted(source_digests),
        "destinations": list(operation_entry.get("destinations", [])),
        "source_digests": source_digests,
        "schema_versions": {"migration": migration_wire_schema_version()},
        "record_counts": dict(operation_entry.get("record_counts", {})),
        "semantic_fingerprints": dict(operation_entry.get("semantic_fingerprints", {})),
        "detected_conflicts": list(operation_entry.get("detected_conflicts", [])),
        "estimated_space_bytes": operation_entry.get("estimated_space_bytes"),
        "backup_location": backups[0]["location"] if backups else None,
        "intended_action": "dry_run",
        "x_operation_owner": operation.owner,
        "x_sase_home": str(context.sase_home),
        "x_home": str(context.home),
    }
    return normalize_manifest(manifest)


def _backup_record(
    backup_id: str,
    *,
    operation_entry: dict[str, Any],
) -> dict[str, Any]:
    manifest_path = backup_dir(backup_id) / "MANIFEST.json"
    if not manifest_path.is_file():
        return {
            "schema_version": 1,
            "backup_id": backup_id,
            "root": "",
            "location": str(backup_dir(backup_id)),
            "verified": False,
            "checksum_manifest": str(backup_dir(backup_id) / "SHA256SUMS"),
        }
    manifest = BackupManifest.from_dict(json.loads(manifest_path.read_text("utf-8")))
    checksum_failures = _verify_backup_checksums(backup_id, manifest)
    sqlite_checks = {
        member.relative_path: member.integrity_check
        for member in manifest.members
        if member.integrity_check is not None
    }
    return {
        "schema_version": 1,
        "backup_id": backup_id,
        "root": manifest.resolved_source_root,
        "location": str(backup_dir(backup_id)),
        "verified": not checksum_failures,
        "checksum_manifest": str(backup_dir(backup_id) / "SHA256SUMS"),
        "source_digest": operation_entry.get("source_digests", {}).get(
            manifest.resolved_source_root
        ),
        "secondary_location": manifest.secondary,
        "source_size_bytes": manifest.total_size_bytes,
        "stored_size_bytes": _stored_size(backup_payload_dir(backup_id)),
        "created_at": manifest.created_at,
        "sqlite_integrity_checks": sqlite_checks,
    }


def _stored_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(
        child.stat().st_size
        for child in path.rglob("*")
        if child.is_file() and not child.is_symlink()
    )


def _verify_backup_checksums(backup_id: str, manifest: BackupManifest) -> list[str]:
    payload_dir = backup_payload_dir(backup_id)
    failures: list[str] = []
    for member in manifest.members:
        if member.sha256 is None:
            continue
        member_path = payload_dir / member.relative_path
        if not member_path.is_file():
            failures.append(f"{member.relative_path}: missing from payload")
            continue
        actual = sha256_file(member_path)
        if actual != member.sha256:
            failures.append(
                f"{member.relative_path}: expected {member.sha256}, got {actual}"
            )
    return failures


def _load_manifest(path: Path) -> dict[str, Any] | MigrationCommandOutcome:
    if not path.is_file():
        return MigrationCommandOutcome(
            False,
            command="manifest",
            dry_run=True,
            message=f"manifest not found: {path}",
            manifest_path=str(path),
            errors=(f"{path}: missing",),
        )
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        return MigrationCommandOutcome(
            False,
            command="manifest",
            dry_run=True,
            message=f"manifest is not a JSON object: {path}",
            manifest_path=str(path),
        )
    return normalize_manifest(value)


def _single_operation_entry(manifest: dict[str, Any]) -> dict[str, Any] | None:
    operations = manifest.get("operations")
    if not isinstance(operations, list) or len(operations) != 1:
        return None
    operation = operations[0]
    return operation if isinstance(operation, dict) else None


def _context_from_manifest(manifest: dict[str, Any]) -> OperationContext:
    run_id = str(manifest.get("run_id") or manifest["manifest_id"])
    backup_ids: list[str] = []
    operation_entry = _single_operation_entry(manifest)
    if operation_entry is not None:
        backup_ids = [str(item) for item in operation_entry.get("backup_ids", [])]
    return OperationContext(
        run_id=run_id,
        sase_home=Path(str(manifest["x_sase_home"])),
        home=Path(str(manifest["x_home"])),
        backup_id=backup_ids[0] if backup_ids else None,
    )


def _manifest_source_digests(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in dict(manifest.get("source_digests", {})).items()
    }


def _observed_source_digests(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        source: digest_path(Path(source))
        for source in _manifest_source_digests(manifest)
    }


def _observed_source_digests_for_replay(
    manifest: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, str]:
    last_state = str(records[-1].get("state")) if records else ""
    if last_state in {"applying", "applied"}:
        return _manifest_source_digests(manifest)
    return _observed_source_digests(manifest)


def _preflight_manifest(
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


def _append_backed_up_if_needed(
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


def _refused(
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


def _operation_name_from_manifest(manifest: dict[str, Any]) -> str | None:
    operation_entry = _single_operation_entry(manifest)
    return str(operation_entry["operation"]) if operation_entry is not None else None


def _host_identity() -> dict[str, str]:
    return {
        "hostname": platform.node() or "unknown",
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


def _repo_revisions() -> dict[str, str]:
    revision = _git_revision(Path.cwd())
    return {"sase": revision} if revision else {}


def _git_revision(root: Path) -> str | None:
    git = root / ".git"
    if not git.exists():
        return None
    head = git / "HEAD"
    try:
        raw = head.read_text("utf-8").strip()
        if raw.startswith("ref: "):
            ref_path = git / raw.removeprefix("ref: ").strip()
            return ref_path.read_text("utf-8").strip()
        return raw
    except OSError:
        return None


def _abort_after_archives_from_env() -> int | None:
    raw = os.environ.get(ABORT_AFTER_ARCHIVES_ENV_VAR)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


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
