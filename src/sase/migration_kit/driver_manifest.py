"""Manifest construction, parsing, and host/repo identity for the migration driver.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

import json
from pathlib import Path
import platform
from typing import Any

from sase.core.time import local_now
from sase.migration_kit.catalog import OperationSpec
from sase.migration_kit.core_contract import (
    migration_wire_schema_version,
    normalize_manifest,
)
from sase.migration_kit.driver_outcome import MigrationCommandOutcome
from sase.migration_kit.operations.base import OperationContext
from sase.migration_kit.operations.util import digest_path


def manifest_for(
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


def load_manifest(path: Path) -> dict[str, Any] | MigrationCommandOutcome:
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


def single_operation_entry(manifest: dict[str, Any]) -> dict[str, Any] | None:
    operations = manifest.get("operations")
    if not isinstance(operations, list) or len(operations) != 1:
        return None
    operation = operations[0]
    return operation if isinstance(operation, dict) else None


def context_from_manifest(manifest: dict[str, Any]) -> OperationContext:
    run_id = str(manifest.get("run_id") or manifest["manifest_id"])
    backup_ids: list[str] = []
    operation_entry = single_operation_entry(manifest)
    if operation_entry is not None:
        backup_ids = [str(item) for item in operation_entry.get("backup_ids", [])]
    return OperationContext(
        run_id=run_id,
        sase_home=Path(str(manifest["x_sase_home"])),
        home=Path(str(manifest["x_home"])),
        backup_id=backup_ids[0] if backup_ids else None,
    )


def manifest_source_digests(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in dict(manifest.get("source_digests", {})).items()
    }


def _observed_source_digests(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        source: digest_path(Path(source))
        for source in manifest_source_digests(manifest)
    }


def observed_source_digests_for_replay(
    manifest: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, str]:
    last_state = str(records[-1].get("state")) if records else ""
    if last_state in {"applying", "applied"}:
        return manifest_source_digests(manifest)
    return _observed_source_digests(manifest)


def operation_name_from_manifest(manifest: dict[str, Any]) -> str | None:
    operation_entry = single_operation_entry(manifest)
    return str(operation_entry["operation"]) if operation_entry is not None else None
