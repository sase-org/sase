"""Hash verification for reviewed gate envelopes and owned resources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.notification_gates.durability import (
    read_json_object,
    request_sha256,
    sha256_file,
    verify_mode,
)
from sase.notification_gates.models import (
    GATE_REQUEST_SCHEMA_VERSION,
    GateChoice,
    GateError,
    validate_identifier,
    validate_relative_path,
)
from sase.notification_gates.paths import assert_owned_bundle, owned_resource_path
from sase.notification_gates.registry import GateAdapter, adapter_for_kind


def load_and_verify_bundle(
    bundle_path: Path,
) -> tuple[dict[str, Any], GateAdapter]:
    """Load a canonical request and verify every recorded reviewed hash."""
    owned_root = assert_owned_bundle(bundle_path)
    request_path = owned_root / "request.json"
    envelope = read_json_object(request_path)
    if envelope.get("schema_version") != GATE_REQUEST_SCHEMA_VERSION:
        raise GateError(
            "unsupported_schema",
            "schema_version",
            f"schema_version must be {GATE_REQUEST_SCHEMA_VERSION}",
        )
    kind = validate_identifier(envelope.get("kind"), "kind")
    request_id = validate_identifier(envelope.get("request_id"), "request_id")
    adapter = adapter_for_kind(kind)
    if owned_root.name != request_id or owned_root.parent.name != adapter.kind:
        raise GateError(
            "bundle_identity_mismatch",
            str(owned_root),
            "bundle path does not match request kind and id",
        )

    hashes = envelope.get("hashes")
    if not isinstance(hashes, dict):
        raise GateError("missing_hashes", "hashes", "request hashes are required")
    expected_request = hashes.get("request")
    actual_request = request_sha256(envelope)
    if expected_request != actual_request:
        raise GateError(
            "hash_mismatch", str(request_path), "canonical request hash changed"
        )
    expected_resources = hashes.get("resources")
    if not isinstance(expected_resources, dict):
        raise GateError(
            "missing_hashes", "hashes.resources", "resource hashes are required"
        )
    resources = envelope.get("resources")
    if not isinstance(resources, list):
        raise GateError("invalid_request", "resources", "resources must be an array")
    declared: set[str] = set()
    for index, raw_resource in enumerate(resources):
        if not isinstance(raw_resource, dict):
            raise GateError(
                "invalid_request", f"resources[{index}]", "resource must be an object"
            )
        relative = validate_relative_path(
            raw_resource.get("path"), f"resources[{index}].path"
        )
        executable = raw_resource.get("executable", False)
        if not isinstance(executable, bool):
            raise GateError(
                "invalid_request",
                f"resources[{index}].executable",
                "executable must be a boolean",
            )
        if relative in declared:
            raise GateError(
                "duplicate_identifier", "resources", f"duplicate resource: {relative}"
            )
        declared.add(relative)
        expected = expected_resources.get(relative)
        if not isinstance(expected, str):
            raise GateError(
                "missing_hashes", relative, f"missing resource hash: {relative}"
            )
        path = owned_resource_path(owned_root, relative)
        verify_mode(path, executable=executable)
        if sha256_file(path) != expected:
            raise GateError(
                "hash_mismatch", relative, f"resource hash changed: {relative}"
            )
    extra_hashes = set(expected_resources) - declared
    if extra_hashes:
        raise GateError(
            "unexpected_hashes",
            "hashes.resources",
            f"hashes reference undeclared resources: {', '.join(sorted(extra_hashes))}",
        )

    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices:
        raise GateError("invalid_request", "choices", "gate has no terminal choices")
    for index, choice in enumerate(choices):
        GateChoice.from_mapping(choice, index)
    return envelope, adapter


__all__ = ["load_and_verify_bundle"]
