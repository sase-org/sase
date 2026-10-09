"""Bundle assembly for the notification-gate creation service.

Builds the durable request envelope, the notification row, and the
creation result every gate creation persists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.core.time import get_timezone
from sase.notification_gates._service_shared import (
    preview_relative_path,
    string_values,
)
from sase.notification_gates.durability import owned_resource_path, request_sha256
from sase.notification_gates.models import (
    GATE_REQUEST_SCHEMA_VERSION,
    GATE_RESULT_SCHEMA_VERSION,
    GateCreationResult,
    GateSpec,
    validate_color,
)
from sase.notification_gates.presentation import (
    GATE_CHIP_COLOR_ACTION_DATA_KEY,
    GATE_CHIP_GLYPH_ACTION_DATA_KEY,
    GATE_CHIP_LABEL_ACTION_DATA_KEY,
    GATE_ORIGIN_AGENT_ACTION_DATA_KEY,
    GATE_PANEL_ACTION_DATA_KEY,
    GATE_PANEL_ICON_ACTION_DATA_KEY,
    GATE_TITLE_ACTION_DATA_KEY,
    GateChip,
    normalize_gate_chip,
    normalize_gate_origin_agent,
    normalize_gate_panel,
    normalize_gate_panel_icon,
    normalize_gate_snooze_until,
    normalize_gate_title,
)
from sase.notification_gates.registry import GateAdapter
from sase.notifications.models import Notification, normalize_notification_tags


def build_gate_envelope(
    spec: GateSpec,
    adapter: GateAdapter,
    *,
    request_id: str,
    notification_id: str | None,
    resource_hashes: dict[str, str],
    policy_block: dict[str, Any],
) -> dict[str, Any]:
    from sase.autonomy.gates import POLICY_BLOCK_KINDS

    created_at = datetime.now(get_timezone())
    presentation = dict(spec.presentation)
    presentation["action"] = adapter.action
    presentation.setdefault("sender", adapter.sender)
    auto_block = spec.auto.to_dict()
    if adapter.kind in POLICY_BLOCK_KINDS:
        auto_block["policy"] = dict(policy_block)
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
        "auto": auto_block,
        "review_revision": 1,
        "hashes": {"resources": resource_hashes},
    }
    if spec.turn is not None:
        envelope["turn"] = spec.turn.to_dict()
    envelope["hashes"]["request"] = request_sha256(envelope)
    return envelope


def build_gate_notification(
    spec: GateSpec,
    adapter: GateAdapter,
    paths: Any,
    notification_id: str,
) -> Notification:
    presentation = spec.presentation
    notes = string_values(presentation.get("notes", []))
    tags = string_values(presentation.get("tags", []))
    files = [
        str(owned_resource_path(paths.root, relative))
        for relative in string_values(presentation.get("files", []))
    ]
    preview = preview_relative_path(spec)
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
    panel = normalize_gate_panel(presentation.get("panel"))
    if panel is not None:
        action_data[GATE_PANEL_ACTION_DATA_KEY] = panel
    panel_icon = normalize_gate_panel_icon(presentation.get("panel_icon"))
    if panel_icon is not None:
        action_data[GATE_PANEL_ICON_ACTION_DATA_KEY] = panel_icon
    chip: GateChip | None = normalize_gate_chip(presentation.get("chip"))
    if chip is not None:
        action_data[GATE_CHIP_GLYPH_ACTION_DATA_KEY] = chip.glyph
        action_data[GATE_CHIP_LABEL_ACTION_DATA_KEY] = chip.label
        if chip.color is not None:
            action_data[GATE_CHIP_COLOR_ACTION_DATA_KEY] = chip.color
    origin_agent = normalize_gate_origin_agent(presentation.get("origin_agent"))
    if origin_agent is not None:
        action_data[GATE_ORIGIN_AGENT_ACTION_DATA_KEY] = origin_agent
    title = normalize_gate_title(presentation.get("title"))
    if title is not None:
        action_data[GATE_TITLE_ACTION_DATA_KEY] = title
    if preview is not None:
        action_data["preview_path"] = str(owned_resource_path(paths.root, preview))
    sender = str(presentation.get("sender", adapter.sender)).strip()
    # A gate that is not actionable until a future instant is born snoozed, so
    # its notification never appears unread in the window between the append
    # here and a snooze applied afterwards.
    snooze_until = normalize_gate_snooze_until(presentation.get("snooze_until"))
    return Notification(
        id=notification_id,
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=sender,
        muted=snooze_until is not None,
        snooze_until=snooze_until,
        icon=(
            str(presentation["icon"]) if presentation.get("icon") is not None else None
        ),
        color=validate_color(presentation.get("color"), "presentation.color"),
        notes=notes,
        files=files,
        tags=normalize_notification_tags(tags),
        action=adapter.action,
        action_data=action_data,
        silent=bool(presentation.get("silent", False)),
    )


def build_gate_creation_result(
    spec: GateSpec,
    adapter: GateAdapter,
    paths: Any,
    envelope: dict[str, Any],
    *,
    notification_id: str | None,
    auto_state: str,
    auto_selected_option_ids: tuple[str, ...] | None,
    policy_block: dict[str, Any],
) -> GateCreationResult:
    from sase.autonomy.gates import POLICY_BLOCK_KINDS

    preview = preview_relative_path(spec)
    auto_resolution: dict[str, Any] = {
        "enabled": spec.auto.enabled,
        "argument": spec.auto.argument,
        "state": auto_state,
        "selected_option_ids": (
            None if auto_selected_option_ids is None else list(auto_selected_option_ids)
        ),
    }
    if adapter.kind in POLICY_BLOCK_KINDS:
        auto_resolution["policy"] = dict(policy_block)
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
        auto_resolution=auto_resolution,
        hashes=dict(envelope["hashes"]),
    )


__all__ = [
    "build_gate_creation_result",
    "build_gate_envelope",
    "build_gate_notification",
]
