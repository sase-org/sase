"""Durable constructor and revision service for notification gates."""

from __future__ import annotations

import shutil
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.core.time import get_timezone
from sase.notification_gates.durability import (
    atomic_write_json,
    canonical_json_bytes,
    file_lock,
    fsync_dir,
    materialize_resource,
    read_json_object,
    request_sha256,
    sha256_bytes,
    sha256_file,
    verify_mode,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import (
    GATE_REQUEST_SCHEMA_VERSION,
    GATE_RESULT_SCHEMA_VERSION,
    GateCreationResult,
    GateError,
    GateSpec,
)
from sase.notification_gates.paths import (
    RESPONSE_FILENAME,
    assert_owned_bundle,
    bundle_paths,
    interaction_requests_dir,
    owned_resource_path,
)
from sase.notification_gates.registry import (
    GateAdapter,
    adapter_for_kind,
    validate_gate_spec,
)
from sase.notifications.models import Notification, normalize_notification_tags

CREATION_JOURNAL_SCHEMA_VERSION = 1


def create_gate(spec_value: Mapping[str, Any] | GateSpec) -> GateCreationResult:
    """Create or repair one durable gate, idempotently by request id."""
    spec = (
        spec_value
        if isinstance(spec_value, GateSpec)
        else GateSpec.from_mapping(spec_value)
    )
    adapter = adapter_for_kind(spec.kind)
    validate_gate_spec(spec, adapter)
    request_id = spec.request_id or f"{adapter.kind}-{uuid4()}"
    paths = bundle_paths(adapter.kind, request_id)
    lock_path = (
        interaction_requests_dir() / ".locks" / adapter.kind / f"{request_id}.lock"
    )
    with file_lock(lock_path):
        if paths.creation_result.is_file():
            return GateCreationResult.from_mapping(
                read_json_object(paths.creation_result)
            )
        journal = _optional_json(paths.journal)
        if journal.get("state") in {"initializing", "failed"}:
            shutil.rmtree(paths.root, ignore_errors=True)
            journal = {}

        if journal:
            return _resume_gate_creation(spec, adapter, paths, journal)
        return _start_gate_creation(spec, adapter, paths)


def _start_gate_creation(
    spec: GateSpec, adapter: GateAdapter, paths: Any
) -> GateCreationResult:
    notification_id = None if spec.auto.enabled else str(uuid4())
    paths.root.mkdir(parents=True, exist_ok=False)
    fsync_dir(paths.root.parent)
    _write_journal(
        paths.journal,
        state="initializing",
        request_id=paths.root.name,
        kind=adapter.kind,
        notification_id=notification_id,
    )
    published = False
    try:
        for resource in spec.resources:
            materialize_resource(paths.root, resource)
        resource_hashes = {
            resource.path: sha256_file(owned_resource_path(paths.root, resource.path))
            for resource in spec.resources
        }
        envelope = _build_envelope(
            spec,
            adapter,
            request_id=paths.root.name,
            notification_id=notification_id,
            resource_hashes=resource_hashes,
        )
        fingerprint = _spec_fingerprint(spec, adapter, resource_hashes)
        atomic_write_json(paths.request, envelope)
        _write_journal(
            paths.journal,
            state="bundle_written",
            request_id=paths.root.name,
            kind=adapter.kind,
            notification_id=notification_id,
            spec_sha256=fingerprint,
        )
        if spec.auto.enabled:
            return _resolve_auto_gate(spec, adapter, paths, envelope, fingerprint)

        assert notification_id is not None
        _write_journal(
            paths.journal,
            state="notification_prepared",
            request_id=paths.root.name,
            kind=adapter.kind,
            notification_id=notification_id,
            spec_sha256=fingerprint,
        )
        notification = _build_notification(spec, adapter, paths, notification_id)
        from sase.notifications.store import append_notification_strict

        append_notification_strict(notification)
        published = True
        return _complete_manual_gate(
            spec, adapter, paths, envelope, fingerprint, notification_id
        )
    except BaseException:
        row_exists = notification_id is not None and _notification_exists(
            notification_id
        )
        if published or row_exists:
            _compensate_published_gate(notification_id, paths)
        else:
            shutil.rmtree(paths.root, ignore_errors=True)
        raise


def _resume_gate_creation(
    spec: GateSpec, adapter: GateAdapter, paths: Any, journal: dict[str, Any]
) -> GateCreationResult:
    state = journal.get("state")
    if state not in {"bundle_written", "notification_prepared"}:
        raise GateError(
            "invalid_creation_state", str(paths.journal), f"unknown gate state: {state}"
        )
    envelope = read_json_object(paths.request)
    candidate_fingerprint = _spec_fingerprint(spec, adapter, _source_hashes(spec))
    if candidate_fingerprint != journal.get("spec_sha256"):
        raise GateError(
            "request_id_conflict",
            paths.root.name,
            "request id already belongs to a different gate specification",
        )
    if spec.auto.enabled:
        return _resolve_auto_gate(
            spec,
            adapter,
            paths,
            envelope,
            candidate_fingerprint,
        )
    notification_id = journal.get("notification_id")
    if not isinstance(notification_id, str) or not notification_id:
        raise GateError(
            "invalid_creation_state",
            str(paths.journal),
            "manual gate journal has no notification id",
        )
    if _notification_exists(notification_id):
        from sase.notifications.pending_actions import register_notification

        notification = _find_notification(notification_id)
        assert notification is not None
        register_notification(notification)
    else:
        notification = _build_notification(spec, adapter, paths, notification_id)
        from sase.notifications.store import append_notification_strict

        append_notification_strict(notification)
    return _complete_manual_gate(
        spec,
        adapter,
        paths,
        envelope,
        candidate_fingerprint,
        notification_id,
    )


def _resolve_auto_gate(
    spec: GateSpec,
    adapter: GateAdapter,
    paths: Any,
    envelope: dict[str, Any],
    fingerprint: str,
) -> GateCreationResult:
    selected_option_ids = adapter.resolve_auto_selection(spec, spec.auto.argument)
    execution = execute_gate_selection(
        paths.root,
        selected_option_ids,
        adapter.automatic_input(spec),
        source="auto_resolution",
    )
    result = _creation_result(
        spec,
        adapter,
        paths,
        envelope,
        notification_id=None,
        auto_state="resolved",
        auto_selected_option_ids=selected_option_ids,
    )
    atomic_write_json(paths.creation_result, result.to_dict())
    _write_journal(
        paths.journal,
        state="auto_resolved",
        request_id=paths.root.name,
        kind=adapter.kind,
        notification_id=None,
        spec_sha256=fingerprint,
        response_selected_option_ids=execution.response.get("selected_option_ids"),
    )
    return result


def _complete_manual_gate(
    spec: GateSpec,
    adapter: GateAdapter,
    paths: Any,
    envelope: dict[str, Any],
    fingerprint: str,
    notification_id: str,
) -> GateCreationResult:
    result = _creation_result(
        spec,
        adapter,
        paths,
        envelope,
        notification_id=notification_id,
        auto_state="disabled",
        auto_selected_option_ids=None,
    )
    atomic_write_json(paths.creation_result, result.to_dict())
    _write_journal(
        paths.journal,
        state="complete",
        request_id=paths.root.name,
        kind=adapter.kind,
        notification_id=notification_id,
        spec_sha256=fingerprint,
    )
    return result


def _build_envelope(
    spec: GateSpec,
    adapter: GateAdapter,
    *,
    request_id: str,
    notification_id: str | None,
    resource_hashes: dict[str, str],
) -> dict[str, Any]:
    created_at = datetime.now(get_timezone())
    presentation = dict(spec.presentation)
    presentation["action"] = adapter.action
    presentation.setdefault("sender", adapter.sender)
    envelope: dict[str, Any] = {
        "schema_version": GATE_REQUEST_SCHEMA_VERSION,
        "request_id": request_id,
        "kind": adapter.kind,
        "notification_id": notification_id,
        "created_at": created_at.isoformat(),
        "created_at_unix": created_at.timestamp(),
        "producer": spec.producer,
        "continuation_mode": spec.continuation_mode,
        "gate_timeout_seconds": spec.gate_timeout_seconds,
        "payload": spec.payload,
        "presentation": presentation,
        "query": spec.query,
        "options": [option.to_dict() for option in spec.options],
        "groups": [group.to_dict() for group in spec.groups],
        "branches": [list(branch) for branch in spec.branches],
        "primary_branch": list(spec.primary_branch),
        "operations": [operation.to_dict() for operation in spec.operations],
        "resources": [resource.envelope_dict() for resource in spec.resources],
        "auto": spec.auto.to_dict(),
        "review_revision": 1,
        "hashes": {"resources": resource_hashes},
    }
    envelope["hashes"]["request"] = request_sha256(envelope)
    return envelope


def _build_notification(
    spec: GateSpec,
    adapter: GateAdapter,
    paths: Any,
    notification_id: str,
) -> Notification:
    presentation = spec.presentation
    notes = _string_values(presentation.get("notes", []))
    tags = _string_values(presentation.get("tags", []))
    files = [
        str(owned_resource_path(paths.root, relative))
        for relative in _string_values(presentation.get("files", []))
    ]
    preview = _preview_relative_path(spec)
    if preview is not None:
        preview_path = str(owned_resource_path(paths.root, preview))
        if preview_path not in files:
            files.append(preview_path)
    raw_action_data = presentation.get("action_data", {})
    action_data = {str(key): str(value) for key, value in dict(raw_action_data).items()}
    action_data.update(
        {
            "request_id": paths.root.name,
            "request_kind": adapter.kind,
            "bundle_path": str(paths.root),
            "request_path": str(paths.request),
            "response_path": str(paths.response),
            adapter.legacy_directory_key: str(paths.root),
        }
    )
    if preview is not None:
        action_data["preview_path"] = str(owned_resource_path(paths.root, preview))
    sender = str(presentation.get("sender", adapter.sender)).strip()
    return Notification(
        id=notification_id,
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=sender,
        icon=(
            str(presentation["icon"]) if presentation.get("icon") is not None else None
        ),
        notes=notes,
        files=files,
        tags=normalize_notification_tags(tags),
        action=adapter.action,
        action_data=action_data,
        silent=bool(presentation.get("silent", False)),
    )


def _creation_result(
    spec: GateSpec,
    adapter: GateAdapter,
    paths: Any,
    envelope: dict[str, Any],
    *,
    notification_id: str | None,
    auto_state: str,
    auto_selected_option_ids: tuple[str, ...] | None,
) -> GateCreationResult:
    preview = _preview_relative_path(spec)
    return GateCreationResult(
        schema_version=GATE_RESULT_SCHEMA_VERSION,
        notification_id=notification_id,
        request_id=paths.root.name,
        kind=adapter.kind,
        bundle_path=paths.root,
        request_path=paths.request,
        response_path=paths.response,
        preview_path=(
            None if preview is None else owned_resource_path(paths.root, preview)
        ),
        continuation_mode=spec.continuation_mode,
        auto_resolution={
            "enabled": spec.auto.enabled,
            "argument": spec.auto.argument,
            "state": auto_state,
            "selected_option_ids": (
                None
                if auto_selected_option_ids is None
                else list(auto_selected_option_ids)
            ),
        },
        hashes=dict(envelope["hashes"]),
    )


def refresh_gate_after_edit(bundle_path: Path, operation_id: str) -> dict[str, Any]:
    """Advance reviewed hashes after an adapter-approved ``edit_file`` operation."""
    bundle_path = assert_owned_bundle(bundle_path)
    with file_lock(bundle_path / ".response.lock"):
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
        operations = envelope.get("operations")
        if not isinstance(operations, list):
            raise GateError("invalid_request", "operations", "operations are missing")
        operation = next(
            (
                raw
                for raw in operations
                if isinstance(raw, dict) and raw.get("id") == operation_id
            ),
            None,
        )
        if operation is None or operation.get("kind") != "edit_file":
            raise GateError(
                "unknown_operation", operation_id, "edit operation is not present"
            )
        target = str(operation.get("target"))
        resources = envelope.get("resources")
        if not isinstance(resources, list):
            raise GateError("invalid_request", "resources", "resources are missing")
        expected_hashes = dict(envelope.get("hashes", {}).get("resources", {}))
        for raw_resource in resources:
            if not isinstance(raw_resource, dict):
                raise GateError("invalid_request", "resources", "invalid resource")
            relative = str(raw_resource.get("path"))
            path = owned_resource_path(bundle_path, relative)
            verify_mode(path, executable=bool(raw_resource.get("executable", False)))
            if relative != target and sha256_file(path) != expected_hashes.get(
                relative
            ):
                raise GateError(
                    "hash_mismatch", relative, f"unrelated resource changed: {relative}"
                )
        target_path = owned_resource_path(bundle_path, target)
        adapter.validate_edited_resource(path=target_path)
        adapter.regenerate_previews(bundle_path=bundle_path)
        resource_hashes = {
            str(raw["path"]): sha256_file(
                owned_resource_path(bundle_path, str(raw["path"]))
            )
            for raw in resources
            if isinstance(raw, dict) and "path" in raw
        }
        envelope["review_revision"] = int(envelope.get("review_revision", 1)) + 1
        envelope["hashes"] = {"resources": resource_hashes}
        envelope["hashes"]["request"] = request_sha256(envelope)
        atomic_write_json(request_path, envelope)
        return dict(envelope["hashes"])


def _preview_relative_path(spec: GateSpec) -> str | None:
    explicit = spec.presentation.get("preview")
    if isinstance(explicit, str):
        return explicit
    return next(
        (resource.path for resource in spec.resources if resource.role == "preview"),
        None,
    )


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value] if isinstance(value, list) else []


def _write_journal(path: Path, *, state: str, **fields: Any) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": CREATION_JOURNAL_SCHEMA_VERSION,
            "state": state,
            "updated_at_unix": time.time(),
            **fields,
        },
    )


def _optional_json(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path)
    except GateError as exc:
        if exc.code == "missing_file":
            return {}
        raise


def _source_hashes(spec: GateSpec) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for resource in spec.resources:
        if resource.content is not None:
            hashes[resource.path] = sha256_bytes(resource.content.encode("utf-8"))
        else:
            assert resource.source is not None
            hashes[resource.path] = sha256_file(resource.source)
    return hashes


def _spec_fingerprint(
    spec: GateSpec, adapter: GateAdapter, resource_hashes: dict[str, str]
) -> str:
    value = {
        "kind": adapter.kind,
        "producer": spec.producer,
        "continuation_mode": spec.continuation_mode,
        "gate_timeout_seconds": spec.gate_timeout_seconds,
        "payload": spec.payload,
        "presentation": spec.presentation,
        "query": spec.query,
        "options": [option.to_dict() for option in spec.options],
        "groups": [group.to_dict() for group in spec.groups],
        "branches": [list(branch) for branch in spec.branches],
        "primary_branch": list(spec.primary_branch),
        "operations": [operation.to_dict() for operation in spec.operations],
        "resources": [resource.envelope_dict() for resource in spec.resources],
        "resource_hashes": resource_hashes,
        "auto": spec.auto.to_dict(),
    }
    return sha256_bytes(canonical_json_bytes(value))


def _notification_exists(notification_id: str) -> bool:
    return _find_notification(notification_id) is not None


def _find_notification(notification_id: str) -> Notification | None:
    from sase.notifications.store import load_notifications

    return next(
        (
            notification
            for notification in load_notifications(include_dismissed=True)
            if notification.id == notification_id
        ),
        None,
    )


def _compensate_published_gate(notification_id: str | None, paths: Any) -> None:
    if notification_id is None:
        return
    from sase.notifications.pending_actions import unregister_notification
    from sase.notifications.store import mark_dismissed

    unregister_notification(notification_id)
    mark_dismissed(notification_id)
    try:
        _write_journal(
            paths.journal,
            state="failed",
            request_id=paths.root.name,
            kind=paths.root.parent.name,
            notification_id=notification_id,
        )
    except OSError:
        pass


__all__ = ["create_gate", "refresh_gate_after_edit"]
