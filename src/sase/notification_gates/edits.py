"""Editable-resource actions for notification gates.

An ``edit_file`` action opens a reviewed resource in an editor and accepts the
result only when the kind adapter validates it. Two edit targets exist:

``resource``
    Edit the bundle's own copy. This is the historical behavior and stays the
    default.

``origin``
    Edit the durable file the resource was copied from — for a plan gate, the
    file under ``~/.sase/plans/`` that the reviewer and every other tool
    already point at. The bundle copy stays the reviewed revision and is
    advanced only when the edited origin validates, so a rejected draft is
    never silently discarded: it stays in the origin file, where reopening the
    editor resumes the reviewer's work, and :func:`origin_draft_state` reports
    that the gate is holding an unaccepted draft.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.notification_gates.durability import (
    atomic_write_json,
    file_lock,
    read_json_object,
    request_sha256,
    sha256_file,
    verify_mode,
)
from sase.notification_gates.model_operations import gate_operation_from_envelope
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import (
    RESPONSE_FILENAME,
    assert_owned_bundle,
    open_regular_nofollow,
    owned_resource_path,
)
from sase.notification_gates.registry import adapter_for_kind

OriginDraftState = Literal["clean", "draft", "missing"]


@dataclass(frozen=True)
class EditTarget:
    """The file an ``edit_file`` action opens and the resource it maps to."""

    operation_id: str
    path: Path
    resource_path: str
    origin: Path | None


def resolve_edit_path(
    bundle_path: Path, envelope: Mapping[str, Any], operation_id: str
) -> EditTarget:
    """Return the file one ``edit_file`` action opens.

    Falls back to the bundle resource whenever the action asks for the origin
    but none was recorded — a bundle created before origins existed — or the
    origin file has since been moved or deleted.
    """
    operation = gate_operation_from_envelope(envelope, operation_id, kind="edit_file")
    resource_path = str(operation.target)
    bundle_file = owned_resource_path(bundle_path, resource_path)
    origin = (
        _recorded_origin(envelope, resource_path)
        if operation.edit_target == "origin"
        else None
    )
    return EditTarget(
        operation_id=operation_id,
        path=origin if origin is not None else bundle_file,
        resource_path=resource_path,
        origin=origin,
    )


def refresh_gate_after_edit(bundle_path: Path, operation_id: str) -> dict[str, Any]:
    """Advance reviewed hashes after an adapter-approved ``edit_file`` action."""
    bundle_path = assert_owned_bundle(bundle_path)
    with file_lock(bundle_path / ".response.lock"):
        return _refresh_after_edit_locked(bundle_path, operation_id)


def accept_edited_origin(bundle_path: Path, operation_id: str) -> dict[str, Any]:
    """Copy an edited origin file into the bundle and accept it, or roll back.

    On validation failure the bundle resource is restored to its pre-copy
    bytes, so the gate keeps its last accepted reviewed revision while the
    reviewer's draft stays in the origin file.
    """
    bundle_path = assert_owned_bundle(bundle_path)
    with file_lock(bundle_path / ".response.lock"):
        envelope = read_json_object(bundle_path / "request.json")
        target = resolve_edit_path(bundle_path, envelope, operation_id)
        if target.origin is None:
            return _refresh_after_edit_locked(bundle_path, operation_id)
        resource_file = owned_resource_path(bundle_path, target.resource_path)
        previous = _read_owned_bytes(resource_file)
        _write_owned_bytes(resource_file, _read_owned_bytes(target.origin))
        try:
            return _refresh_after_edit_locked(bundle_path, operation_id)
        except Exception:
            # Every rejection rolls back, not only ``GateError``: the plan
            # adapter rejects with ``PlanApprovalValidationError``, and a
            # narrower clause would leave the bundle holding content the
            # reviewer never accepted.
            _write_owned_bytes(resource_file, previous)
            raise


def discard_origin_draft(bundle_path: Path, operation_id: str) -> OriginDraftState:
    """Restore the origin file from the reviewed bundle copy.

    This is the only path in this module that destroys a reviewer's draft, and
    it exists so discarding one is a deliberate, confirmable act rather than a
    side effect of answering the gate.
    """
    bundle_path = assert_owned_bundle(bundle_path)
    with file_lock(bundle_path / ".response.lock"):
        envelope = read_json_object(bundle_path / "request.json")
        target = resolve_edit_path(bundle_path, envelope, operation_id)
        if target.origin is None:
            return "missing"
        resource_file = owned_resource_path(bundle_path, target.resource_path)
        _write_owned_bytes(target.origin, _read_owned_bytes(resource_file))
        return "clean"


def origin_draft_state(bundle_path: Path, operation_id: str) -> OriginDraftState:
    """Report whether an origin file holds an edit the gate never accepted.

    ``clean`` also covers an action that does not edit an origin at all, since
    nothing can be left unaccepted there.
    """
    bundle_path = assert_owned_bundle(bundle_path)
    envelope = read_json_object(bundle_path / "request.json")
    target = resolve_edit_path(bundle_path, envelope, operation_id)
    operation = gate_operation_from_envelope(envelope, operation_id, kind="edit_file")
    if operation.edit_target != "origin":
        return "clean"
    if target.origin is None:
        return "missing"
    expected = envelope.get("hashes", {}).get("resources", {}).get(target.resource_path)
    return "clean" if sha256_file(target.origin) == expected else "draft"


def _refresh_after_edit_locked(bundle_path: Path, operation_id: str) -> dict[str, Any]:
    """Revalidate and re-hash the bundle after one accepted edit."""
    if (bundle_path / RESPONSE_FILENAME).exists():
        raise GateError(
            "already_answered", str(bundle_path), "answered gates cannot be edited"
        )
    request_path = bundle_path / "request.json"
    envelope = read_json_object(request_path)
    if request_sha256(envelope) != envelope.get("hashes", {}).get("request"):
        raise GateError(
            "hash_mismatch", str(request_path), "canonical request hash changed"
        )
    adapter = adapter_for_kind(str(envelope.get("kind")))
    target = str(
        gate_operation_from_envelope(envelope, operation_id, kind="edit_file").target
    )
    resources = envelope.get("resources")
    if not isinstance(resources, list):
        raise GateError("invalid_request", "resources", "resources are missing")
    expected_hashes = dict(envelope.get("hashes", {}).get("resources", {}))
    for raw_resource in resources:
        if not isinstance(raw_resource, Mapping):
            raise GateError("invalid_request", "resources", "invalid resource")
        relative = str(raw_resource.get("path"))
        path = owned_resource_path(bundle_path, relative)
        verify_mode(path, executable=bool(raw_resource.get("executable", False)))
        if relative != target and sha256_file(path) != expected_hashes.get(relative):
            raise GateError(
                "hash_mismatch", relative, f"unrelated resource changed: {relative}"
            )
    adapter.validate_edited_resource(path=owned_resource_path(bundle_path, target))
    adapter.regenerate_previews(bundle_path=bundle_path)
    resource_hashes = {
        str(raw["path"]): sha256_file(
            owned_resource_path(bundle_path, str(raw["path"]))
        )
        for raw in resources
        if isinstance(raw, Mapping) and "path" in raw
    }
    envelope["review_revision"] = int(envelope.get("review_revision", 1)) + 1
    envelope["hashes"] = {"resources": resource_hashes}
    envelope["hashes"]["request"] = request_sha256(envelope)
    atomic_write_json(request_path, envelope)
    return dict(envelope["hashes"])


def _recorded_origin(envelope: Mapping[str, Any], resource_path: str) -> Path | None:
    resources = envelope.get("resources")
    if not isinstance(resources, list):
        return None
    for raw in resources:
        if not isinstance(raw, Mapping) or str(raw.get("path")) != resource_path:
            continue
        origin = raw.get("origin")
        if not isinstance(origin, str) or not origin:
            return None
        candidate = Path(origin)
        return candidate if candidate.is_file() else None
    return None


def _read_owned_bytes(path: Path) -> bytes:
    fd = open_regular_nofollow(path)
    try:
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _write_owned_bytes(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
    try:
        os.write(fd, content)
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "EditTarget",
    "accept_edited_origin",
    "discard_origin_draft",
    "origin_draft_state",
    "refresh_gate_after_edit",
    "resolve_edit_path",
]
