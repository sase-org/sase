"""Public v2 sidecar I/O API and transactional payload writes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import tempfile

from sase.agents_sync.io import (
    AgentsSyncFormatError,
    atomic_write_bytes,
    canonical_json_bytes,
)
from sase.agents_sync.v2_manifest_io import (
    check_manifest_write_size as check_manifest_write_size,
    decode_owner_manifest as _owner_manifest_from_json,
    owner_hood_directory_names as owner_hood_directory_names,
    owner_manifest_from_bytes as owner_manifest_from_bytes,
    owner_manifest_path as owner_manifest_path,
    read_all_owner_manifests as read_all_owner_manifests,
    read_all_owner_manifests_lenient as read_all_owner_manifests_lenient,
    read_owner_manifest as read_owner_manifest,
)
from sase.agents_sync.v2_models import V2FileReference, V2_SCHEMA_VERSION
from sase.agents_sync.v2_snapshot_io import (
    decode_hood_snapshot as _hood_snapshot_from_json,
    read_hood_snapshot as read_hood_snapshot,
    validate_snapshot as validate_snapshot,
)
from sase.agents_sync.v2_validation import (
    MAX_CONTAINERS as MAX_CONTAINERS,
    MAX_FILES as MAX_FILES,
    MAX_JSON_BYTES as MAX_JSON_BYTES,
    MAX_MANIFEST_HOODS as MAX_MANIFEST_HOODS,
    MAX_MANIFEST_JSON_BYTES as MAX_MANIFEST_JSON_BYTES,
    MAX_OUTPUT_VARIABLE_DEPTH as MAX_OUTPUT_VARIABLE_DEPTH,
    MAX_OUTPUT_VARIABLE_ENCODED_BYTES as MAX_OUTPUT_VARIABLE_ENCODED_BYTES,
    MAX_OUTPUT_VARIABLE_NODES as MAX_OUTPUT_VARIABLE_NODES,
    MAX_OUTPUT_VARIABLES as MAX_OUTPUT_VARIABLES,
    MAX_OUTPUT_VARIABLE_VALUE_BYTES as MAX_OUTPUT_VARIABLE_VALUE_BYTES,
    MAX_PAYLOAD_BYTES as MAX_PAYLOAD_BYTES,
    MAX_RELATIONSHIPS as MAX_RELATIONSHIPS,
    MAX_RUNS as MAX_RUNS,
    MAX_TEXT_BYTES as MAX_TEXT_BYTES,
    V2_METADATA_FIELDS as V2_METADATA_FIELDS,
    is_valid_output_variable_key as is_valid_output_variable_key,
    validate_component as validate_component,
    validate_output_variables as validate_output_variables,
    validate_relative_path as validate_relative_path,
)
from sase.core.agent_publication_batches import (
    AgentPublicationPathRecord,
    plan_agent_publication_batches,
)


@dataclass(frozen=True)
class _PayloadWrite:
    relative: str
    destination: Path
    content: bytes


def v2_json_bytes(value: object) -> bytes:
    """Return the persisted canonical JSON representation."""

    return canonical_json_bytes(value) + b"\n"


def content_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_reference(path: str, payload: bytes) -> V2FileReference:
    validate_relative_path(path)
    return V2FileReference(path, content_digest(payload), len(payload))


def v2_schema_document() -> dict[str, object]:
    return {
        "schema_version": V2_SCHEMA_VERSION,
        "format": "sase-agents-sidecar",
        "authority": "owner-sharded",
        "relationship_schema_version": V2_SCHEMA_VERSION,
    }


def apply_payload_atomic(repo_root: Path, payload: Mapping[str, bytes]) -> bool:
    """Apply a complete prebuilt payload, restoring prior bytes on failure."""

    ordered = sorted(payload.items())
    if sum(len(value) for _path, value in ordered) > MAX_PAYLOAD_BYTES:
        raise AgentsSyncFormatError("publication payload exceeds the byte limit")
    resolved = _resolve_payload(repo_root, ordered)
    changed = _changed_payload(resolved)
    if not changed:
        return False
    return _apply_changed_payload(
        repo_root,
        changed,
        (tuple(item.relative for item in changed),),
    )


def apply_payload_batched_atomic(
    repo_root: Path,
    payload: Mapping[str, bytes],
    *,
    batch_budget_bytes: int = MAX_PAYLOAD_BYTES,
) -> bool:
    """Apply a full reconciliation payload in byte-bounded write batches."""

    resolved = _resolve_payload(repo_root, sorted(payload.items()))
    changed = _changed_payload(resolved)
    if not changed:
        return False
    plan = plan_agent_publication_batches(
        (
            AgentPublicationPathRecord(item.relative, len(item.content))
            for item in changed
        ),
        budget_bytes=batch_budget_bytes,
    )
    batches = tuple(batch.paths for batch in plan.batches)
    if tuple(path for batch in batches for path in batch) != tuple(
        item.relative for item in changed
    ):
        raise RuntimeError(
            "sase_core_rs returned an invalid agent publication batch plan"
        )
    return _apply_changed_payload(
        repo_root,
        changed,
        batches,
    )


def _resolve_payload(
    repo_root: Path, ordered: list[tuple[str, bytes]]
) -> list[_PayloadWrite]:
    root = repo_root.resolve(strict=False)
    resolved: list[_PayloadWrite] = []
    for relative, content in ordered:
        validate_relative_path(relative)
        destination = repo_root / relative
        if not destination.resolve(strict=False).is_relative_to(root):
            raise AgentsSyncFormatError(f"publication escapes repository: {relative!r}")
        resolved.append(_PayloadWrite(relative, destination, bytes(content)))
    return resolved


def _changed_payload(resolved: list[_PayloadWrite]) -> list[_PayloadWrite]:
    changed = [item for item in resolved if _payload_destination_changed(item)]
    return changed


def _payload_destination_changed(item: _PayloadWrite) -> bool:
    if item.destination.exists() and not item.destination.is_file():
        raise AgentsSyncFormatError(
            f"publication destination is not a file: {item.relative!r}"
        )
    return (
        not item.destination.is_file() or item.destination.read_bytes() != item.content
    )


def _apply_changed_payload(
    repo_root: Path,
    changed: list[_PayloadWrite],
    batches: tuple[tuple[str, ...], ...],
) -> bool:
    stage = Path(tempfile.mkdtemp(prefix=".sase-v2-stage-", dir=repo_root))
    backup_root = Path(tempfile.mkdtemp(prefix=".sase-v2-backup-", dir=repo_root))
    changed_by_relative = {item.relative: item for item in changed}
    backups: dict[str, Path | None] = {}
    writes_started = False
    try:
        _stage_changed_payload(stage, changed)
        backups = _backup_changed_payload(backup_root, changed)
        for batch in batches:
            for relative in batch:
                item = changed_by_relative[relative]
                writes_started = True
                atomic_write_bytes(
                    item.destination, (stage / item.relative).read_bytes()
                )
    except Exception as error:
        rollback_errors = (
            _rollback_changed_payload(changed, backups) if writes_started else ()
        )
        cleanup_errors = _cleanup_transaction_dirs((stage, backup_root))
        if rollback_errors or cleanup_errors:
            details = "; ".join((*rollback_errors, *cleanup_errors))
            raise RuntimeError(
                f"publication apply failed and cleanup was incomplete: {details}"
            ) from error
        raise
    cleanup_errors = _cleanup_transaction_dirs((stage, backup_root))
    if cleanup_errors:
        raise RuntimeError(
            "publication apply succeeded but cleanup was incomplete: "
            + "; ".join(cleanup_errors)
        )
    return True


def _stage_changed_payload(stage: Path, changed: list[_PayloadWrite]) -> None:
    for item in changed:
        staged = stage / item.relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(item.content)


def _backup_changed_payload(
    backup_root: Path, changed: list[_PayloadWrite]
) -> dict[str, Path | None]:
    backups: dict[str, Path | None] = {}
    for item in changed:
        if item.destination.is_file():
            backup = backup_root / item.relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.destination, backup)
            backups[item.relative] = backup
        else:
            backups[item.relative] = None
    return backups


def _rollback_changed_payload(
    changed: list[_PayloadWrite], backups: dict[str, Path | None]
) -> tuple[str, ...]:
    errors: list[str] = []
    for item in reversed(changed):
        try:
            original = backups.get(item.relative)
            if original is None:
                try:
                    item.destination.unlink()
                except FileNotFoundError:
                    pass
            else:
                atomic_write_bytes(item.destination, original.read_bytes())
        except Exception as exc:  # pragma: no cover - defensive diagnostic path
            errors.append(f"rollback failed for {item.relative!r}: {exc}")
    return tuple(errors)


def _cleanup_transaction_dirs(paths: tuple[Path, ...]) -> tuple[str, ...]:
    errors: list[str] = []
    for path in paths:
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass
        except Exception as exc:  # pragma: no cover - filesystem-specific
            errors.append(f"temporary directory {path} could not be removed: {exc}")
    return tuple(errors)


__all__ = [
    "MAX_JSON_BYTES",
    "MAX_MANIFEST_HOODS",
    "MAX_MANIFEST_JSON_BYTES",
    "MAX_OUTPUT_VARIABLE_DEPTH",
    "MAX_OUTPUT_VARIABLE_ENCODED_BYTES",
    "MAX_OUTPUT_VARIABLE_NODES",
    "MAX_OUTPUT_VARIABLES",
    "MAX_OUTPUT_VARIABLE_VALUE_BYTES",
    "MAX_TEXT_BYTES",
    "V2_METADATA_FIELDS",
    "apply_payload_atomic",
    "apply_payload_batched_atomic",
    "check_manifest_write_size",
    "content_digest",
    "file_reference",
    "owner_hood_directory_names",
    "owner_manifest_path",
    "owner_manifest_from_bytes",
    "read_all_owner_manifests",
    "read_all_owner_manifests_lenient",
    "read_hood_snapshot",
    "read_owner_manifest",
    "is_valid_output_variable_key",
    "v2_json_bytes",
    "v2_schema_document",
    "validate_component",
    "validate_output_variables",
    "validate_relative_path",
    "validate_snapshot",
]
