"""Legacy proc-residue reconciliation and archive operation.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.migration_kit.catalog import get_operation_spec
from sase.migration_kit.core_contract import reconcile_procs
from sase.migration_kit.operations.base import OperationContext, OperationOutcome
from sase.migration_kit.operations.util import (
    archive_remove_actions,
    digest_path,
    find_symlink_escapes,
    fingerprint_json,
    read_jsonl,
)


class ProcsResidueOperation:
    """Archive ``~/.sase/tasks`` only when every row matches canonical procs."""

    spec = get_operation_spec("procs-residue")

    def plan(self, context: OperationContext) -> dict[str, Any]:
        legacy_dir = context.sase_home / "tasks"
        legacy_store = legacy_dir / "tasks.jsonl"
        canonical_store = context.sase_home / "procs" / "procs.jsonl"
        legacy_rows = _legacy_rows(legacy_store)
        canonical_rows = _canonical_rows(canonical_store)
        reconcile = reconcile_procs(legacy_rows, canonical_rows)
        conflicts = _conflicts_from_reconcile(reconcile, legacy_store)
        source_digests = {
            str(legacy_dir): digest_path(legacy_dir),
            str(canonical_store): digest_path(canonical_store),
        }
        source_paths = sorted(source_digests)
        actions: list[dict[str, Any]] = []
        if legacy_rows and not conflicts:
            escapes = find_symlink_escapes(context.sase_home, legacy_dir)
            if escapes:
                conflicts.append(
                    {
                        "schema_version": 1,
                        "path": str(legacy_dir),
                        "kind": "symlink_escape",
                        "detail": "; ".join(escapes),
                    }
                )
            else:
                actions.append(
                    {
                        "action_id": "legacy-tasks",
                        "kind": "archive_remove",
                        "source": str(legacy_dir),
                        "source_digest": source_digests[str(legacy_dir)],
                        "matched_proc_ids": [
                            str(match["proc_id"])
                            for match in reconcile.get("matched", [])
                            if isinstance(match, dict)
                        ],
                    }
                )

        semantic_payload = {
            "legacy": legacy_rows,
            "canonical": canonical_rows,
            "reconcile": reconcile,
        }
        return {
            "schema_version": 1,
            "operation": self.spec.name,
            "roots": [str(legacy_dir), str(context.sase_home / "procs")],
            "source_paths": source_paths,
            "destinations": [],
            "source_digests": source_digests,
            "schema_versions": {"migration": 1},
            "record_counts": {
                "legacy_rows": len(legacy_rows),
                "canonical_rows": len(canonical_rows),
                "matched": len(reconcile.get("matched", [])),
                "conflicting": len(reconcile.get("conflicting", [])),
                "unmatched_legacy": len(reconcile.get("unmatched_legacy", [])),
            },
            "semantic_fingerprints": {
                "procs-residue": fingerprint_json(semantic_payload)
            },
            "detected_conflicts": conflicts,
            "estimated_space_bytes": _tree_size(legacy_dir),
            "backup_required": self.spec.backup_required,
            "backup_ids": [context.backup_id] if context.backup_id else [],
            "preconditions": list(self.spec.preconditions),
            "verification_query": {
                "matched_proc_ids": [
                    str(match["proc_id"])
                    for match in reconcile.get("matched", [])
                    if isinstance(match, dict)
                ],
                "legacy_store": str(legacy_store),
                "canonical_store": str(canonical_store),
            },
            "rollback_unit": self.spec.rollback_unit,
            "intended_action": "dry_run",
            "x_actions": actions,
            "x_reconcile": reconcile,
        }

    def apply(
        self, context: OperationContext, operation_entry: dict[str, Any]
    ) -> OperationOutcome:
        return archive_remove_actions(
            context=context,
            operation=self.spec.name,
            operation_entry=operation_entry,
        )

    def verify(
        self, context: OperationContext, operation_entry: dict[str, Any]
    ) -> OperationOutcome:
        legacy_store = context.sase_home / "tasks" / "tasks.jsonl"
        failures: list[str] = []
        if legacy_store.exists():
            failures.append(f"{legacy_store}: legacy store still exists")

        expected_ids = set(
            operation_entry.get("verification_query", {}).get("matched_proc_ids", [])
        )
        canonical_ids = {
            str(row["proc_id"])
            for row in _canonical_rows(context.sase_home / "procs" / "procs.jsonl")
            if row.get("proc_id")
        }
        missing = sorted(expected_ids - canonical_ids)
        if missing:
            failures.append("canonical proc record(s) missing: " + ", ".join(missing))
        return OperationOutcome(
            not failures,
            "proc residue post-conditions verified"
            if not failures
            else "proc residue verification failed",
            errors=tuple(failures),
        )


def _legacy_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for row in read_jsonl(path):
        normalized = dict(row)
        proc_id = normalized.get("proc_id") or normalized.get("task_id")
        if proc_id is not None:
            normalized.setdefault("proc_id", proc_id)
        normalized.setdefault(
            "semantic_fingerprint", fingerprint_json(_semantic_proc_record(normalized))
        )
        rows.append(normalized)
    return rows


def _canonical_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for row in read_jsonl(path):
        normalized = dict(row)
        normalized.setdefault(
            "semantic_fingerprint", fingerprint_json(_semantic_proc_record(normalized))
        )
        rows.append(normalized)
    return rows


def _semantic_proc_record(row: dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    if "task_id" in record and "proc_id" not in record:
        record["proc_id"] = record["task_id"]
    record.pop("task_id", None)
    log_path = record.get("log_path")
    if isinstance(log_path, str):
        record["log_path"] = Path(log_path).name
    return record


def _conflicts_from_reconcile(
    reconcile: dict[str, Any], legacy_store: Path
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for row in reconcile.get("unmatched_legacy", []):
        if isinstance(row, dict):
            proc_id = row.get("proc_id") or row.get("task_id") or "<unknown>"
            conflicts.append(
                {
                    "schema_version": 1,
                    "path": str(legacy_store),
                    "kind": "unmatched_legacy_proc",
                    "detail": f"legacy row has no canonical counterpart: {proc_id}",
                }
            )
    for row in reconcile.get("conflicting", []):
        if isinstance(row, dict):
            conflicts.append(
                {
                    "schema_version": 1,
                    "path": str(legacy_store),
                    "kind": "conflicting_proc",
                    "detail": str(row.get("reason") or row),
                }
            )
    return conflicts


def _tree_size(root: Path) -> int:
    if root.is_file():
        return root.stat().st_size
    if not root.is_dir():
        return 0
    return sum(
        path.stat().st_size
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


__all__ = ["ProcsResidueOperation"]
