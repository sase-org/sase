"""Public v2 sidecar I/O API and transactional payload writes."""

from __future__ import annotations

from collections.abc import Mapping
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

    root = repo_root.resolve(strict=False)
    ordered = sorted(payload.items())
    if sum(len(value) for _path, value in ordered) > MAX_PAYLOAD_BYTES:
        raise AgentsSyncFormatError("publication payload exceeds the byte limit")
    resolved: list[tuple[str, Path, bytes]] = []
    for relative, content in ordered:
        validate_relative_path(relative)
        destination = repo_root / relative
        if not destination.resolve(strict=False).is_relative_to(root):
            raise AgentsSyncFormatError(f"publication escapes repository: {relative!r}")
        resolved.append((relative, destination, bytes(content)))
    changed = [
        item
        for item in resolved
        if not item[1].is_file() or item[1].read_bytes() != item[2]
    ]
    if not changed:
        return False

    stage = Path(tempfile.mkdtemp(prefix=".sase-v2-stage-", dir=repo_root))
    backups: dict[Path, bytes | None] = {}
    try:
        for relative, _destination, content in changed:
            staged = stage / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(content)
        for relative, destination, _content in changed:
            backups[destination] = (
                destination.read_bytes() if destination.is_file() else None
            )
            atomic_write_bytes(destination, (stage / relative).read_bytes())
    except Exception:
        for destination, original in reversed(tuple(backups.items())):
            if original is None:
                try:
                    destination.unlink()
                except FileNotFoundError:
                    pass
            else:
                atomic_write_bytes(destination, original)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return True


__all__ = [
    "MAX_JSON_BYTES",
    "MAX_OUTPUT_VARIABLE_DEPTH",
    "MAX_OUTPUT_VARIABLE_ENCODED_BYTES",
    "MAX_OUTPUT_VARIABLE_NODES",
    "MAX_OUTPUT_VARIABLES",
    "MAX_OUTPUT_VARIABLE_VALUE_BYTES",
    "MAX_TEXT_BYTES",
    "V2_METADATA_FIELDS",
    "apply_payload_atomic",
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
