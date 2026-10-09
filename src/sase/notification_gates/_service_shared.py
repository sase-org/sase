"""Shared low-level helpers for the ``service`` split modules.

This module is private (``_``-prefixed) so the split can share helpers
without importing ``_``-prefixed names across files: everything defined
here carries a public name, and every consumer lives in one of the
``service_*`` sibling modules.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sase.notification_gates.durability import (
    atomic_write_json,
    canonical_json_bytes,
    read_json_object,
    sha256_bytes,
    sha256_file,
)
from sase.notification_gates.models import GateError, GateSpec
from sase.notification_gates.registry import GateAdapter
from sase.notifications.models import Notification

CREATION_JOURNAL_SCHEMA_VERSION = 1


def preview_relative_path(spec: GateSpec) -> str | None:
    explicit = spec.presentation.get("preview")
    if isinstance(explicit, str):
        return explicit
    return next(
        (resource.path for resource in spec.resources if resource.role == "preview"),
        None,
    )


def string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value] if isinstance(value, list) else []


def write_journal(path: Path, *, state: str, **fields: Any) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": CREATION_JOURNAL_SCHEMA_VERSION,
            "state": state,
            "updated_at_unix": time.time(),
            **fields,
        },
    )


def optional_json(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path)
    except GateError as exc:
        if exc.code == "missing_file":
            return {}
        raise


def source_hashes(spec: GateSpec) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for resource in spec.resources:
        if resource.content is not None:
            hashes[resource.path] = sha256_bytes(resource.content.encode("utf-8"))
        else:
            assert resource.source is not None
            hashes[resource.path] = sha256_file(resource.source)
    return hashes


def spec_fingerprint(
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
        "turn": None if spec.turn is None else spec.turn.to_dict(),
    }
    return sha256_bytes(canonical_json_bytes(value))


def notification_exists(notification_id: str) -> bool:
    return find_notification(notification_id) is not None


def find_notification(notification_id: str) -> Notification | None:
    from sase.notifications.store import load_notifications

    return next(
        (
            notification
            for notification in load_notifications(include_dismissed=True)
            if notification.id == notification_id
        ),
        None,
    )


__all__ = [
    "CREATION_JOURNAL_SCHEMA_VERSION",
    "find_notification",
    "notification_exists",
    "optional_json",
    "preview_relative_path",
    "source_hashes",
    "spec_fingerprint",
    "string_values",
    "write_journal",
]
