"""Import-leg purge wrapper operation.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from typing import Any
from collections.abc import Iterator

from sase.migration_kit.catalog import get_operation_spec
from sase.migration_kit.operations.base import OperationContext, OperationOutcome
from sase.migration_kit.operations.util import digest_path, fingerprint_json


class ImportPurgeOperation:
    """Wrap the supported local import-state purge behind driver gates."""

    spec = get_operation_spec("import-purge")

    def plan(self, context: OperationContext) -> dict[str, Any]:
        source_roots = _source_roots(context)
        with _temporary_sase_home(context.sase_home):
            from sase.agents_sync.purge_local_state import purge_local_import_state

            preview = purge_local_import_state(apply=False)
        preview_payload = preview.to_json_dict()
        source_digests = {str(path): digest_path(path) for path in source_roots}
        return {
            "schema_version": 1,
            "operation": self.spec.name,
            "roots": [str(path) for path in source_roots],
            "source_paths": sorted(source_digests),
            "destinations": [],
            "source_digests": source_digests,
            "schema_versions": {"migration": 1},
            "record_counts": _record_counts(preview_payload),
            "semantic_fingerprints": {
                "import-purge-preview": fingerprint_json(preview_payload)
            },
            "detected_conflicts": [],
            "estimated_space_bytes": 0,
            "backup_required": self.spec.backup_required,
            "backup_ids": [context.backup_id] if context.backup_id else [],
            "preconditions": list(self.spec.preconditions),
            "verification_query": {
                "preview": preview_payload,
                "doctor": "sase agent names purge-local-state dry run",
            },
            "rollback_unit": self.spec.rollback_unit,
            "intended_action": "dry_run",
            "x_actions": [{"action_id": "purge-local-state", "kind": "import_purge"}],
        }

    def apply(
        self, context: OperationContext, operation_entry: dict[str, Any]
    ) -> OperationOutcome:
        with _temporary_sase_home(context.sase_home):
            from sase.agents_sync.purge_local_state import purge_local_import_state

            outcome = purge_local_import_state(apply=True)
        payload = outcome.to_json_dict()
        raw_errors = payload.get("errors", [])
        errors = (
            tuple(str(error) for error in raw_errors)
            if isinstance(raw_errors, list)
            else (str(raw_errors),)
            if raw_errors
            else ()
        )
        return OperationOutcome(
            outcome.ok,
            "local import state purged"
            if outcome.ok
            else "local import-state purge failed",
            errors=errors,
            details={"purge": payload},
        )

    def verify(
        self, context: OperationContext, operation_entry: dict[str, Any]
    ) -> OperationOutcome:
        with _temporary_sase_home(context.sase_home):
            from sase.agents_sync.purge_local_state import purge_local_import_state

            preview = purge_local_import_state(apply=False)
        payload = preview.to_json_dict()
        empty = bool(preview.is_empty)
        raw_surviving = payload.get("surviving_import_names", [])
        surviving: tuple[str, ...] = (
            tuple(str(item) for item in raw_surviving)
            if isinstance(raw_surviving, list)
            else (str(raw_surviving),)
            if raw_surviving
            else ()
        )
        return OperationOutcome(
            empty and not surviving,
            "local import-state purge verified"
            if empty and not surviving
            else "local import-state residue remains",
            errors=surviving,
            details={"preview": payload},
        )


def _source_roots(context: OperationContext) -> tuple[Path, ...]:
    return (
        context.sase_home / "agents_sync",
        context.sase_home / "artifacts",
        context.sase_home / "chats",
        context.sase_home / "dismissed_bundles",
        context.sase_home / "projects",
    )


def _record_counts(payload: dict[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, value in payload.items():
        if isinstance(value, list):
            counts[key] = len(value)
    return counts


@contextmanager
def _temporary_sase_home(path: Path) -> Iterator[None]:
    previous = os.environ.get("SASE_HOME")
    os.environ["SASE_HOME"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SASE_HOME", None)
        else:
            os.environ["SASE_HOME"] = previous


__all__ = ["ImportPurgeOperation"]
