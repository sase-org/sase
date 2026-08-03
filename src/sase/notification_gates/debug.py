"""Best-effort, bounded diagnostics for notification gate bundles."""

from __future__ import annotations

import dataclasses
import math
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.notification_gates.debug_artifacts import (
    MAX_ARTIFACT_BYTES,
    MAX_ERROR_EXCERPT_BYTES,
    bound_text,
    error_artifacts,
    notification_row_artifact,
    parsed_json,
    read_json_artifact,
    resource_integrity,
    terminal_artifact,
)
from sase.notification_gates.debug_models import (
    GateDebugArtifact,
    GateDebugBundlePaths,
    GateDebugContext,
    GateDebugError as _GateDebugError,
    GateDebugResource as _GateDebugResource,
    GateDebugSnapshot,
    GateDebugStatus,
)
from sase.notification_gates.debug_rendering import (
    build_gate_debug_overview,
    build_no_bundle_overview,
    iso_from_unix,
)
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    REQUEST_FILENAME,
    RESPONSE_FILENAME,
    bundle_paths,
    resolve_action_bundle,
)
from sase.notification_gates.registry import adapter_for_action
from sase.notifications.models import Notification


def debug_context_from_notification(notification: Notification) -> GateDebugContext:
    """Copy a notification into context safe to retain behind another modal."""
    copied = dataclasses.replace(
        notification,
        notes=list(notification.notes),
        files=list(notification.files),
        tags=list(notification.tags),
        action_data=dict(notification.action_data),
    )
    return GateDebugContext(copied, dict(notification.action_data))


def build_gate_debug_snapshot(
    notification_row: Notification | Mapping[str, Any],
    action_data: Mapping[str, str] | None = None,
    *,
    now: float | None = None,
) -> GateDebugSnapshot:
    """Build a diagnostic snapshot; malformed or missing input never escapes."""
    current = time.time() if now is None else now
    notification = _coerce_notification(notification_row)
    projected_action_data = dict(action_data or notification.action_data)
    kind = _kind_for(notification.action, projected_action_data)
    request_id = str(projected_action_data.get("request_id") or notification.id)
    icon = notification.icon or _icon_for_action(notification.action)
    paths = _resolve_paths(notification.action, projected_action_data)

    if paths is None:
        empty = "No gate bundle attached to this notification."
        request = GateDebugArtifact("missing", empty, empty)
        response = GateDebugArtifact("missing", empty, empty)
        errors_artifact = GateDebugArtifact("missing", empty, empty)
        row = notification_row_artifact(notification)
        overview_text = build_no_bundle_overview(notification, kind, request_id)
        return GateDebugSnapshot(
            kind=kind,
            request_id=request_id,
            notification_id=notification.id,
            icon=icon,
            status="UNKNOWN",
            created_at=notification.timestamp or None,
            age=_format_age(_timestamp(notification.timestamp), current),
            bundle_path=None,
            overview=GateDebugArtifact("missing", overview_text, overview_text),
            request=request,
            response=response,
            errors=(),
            error_count=0,
            errors_artifact=errors_artifact,
            row=row,
            resources=(),
        )

    request = read_json_artifact(paths.request, label=paths.request.name)
    envelope = parsed_json(request)
    kind = str(envelope.get("kind") or kind) if envelope else kind
    request_id = (
        str(envelope.get("request_id") or request_id) if envelope else request_id
    )
    response, terminal_payload, terminal_kind = terminal_artifact(paths)
    errors, error_count, errors_artifact = error_artifacts(paths.root / "errors")
    resources = resource_integrity(paths.root, envelope)
    row = notification_row_artifact(notification)

    created_at, created_unix = _created_time(envelope, notification.timestamp)
    timeout = _number(envelope.get("gate_timeout_seconds")) if envelope else None
    deadline = None
    if created_unix is not None and timeout is not None:
        deadline = created_unix + timeout
    status = _derive_status(
        request,
        response,
        terminal_kind=terminal_kind,
        terminal_payload=terminal_payload,
        deadline=deadline,
        now=current,
    )
    overview_text = build_gate_debug_overview(
        notification,
        kind=kind,
        request_id=request_id,
        bundle_root=paths.root,
        legacy=paths.legacy,
        envelope=envelope,
        request_status=request.status,
        response_status=response.status,
        terminal_payload=terminal_payload,
        terminal_kind=terminal_kind,
        resources=resources,
        error_count=error_count,
        status=status,
        created_at=created_at,
        created_unix=created_unix,
        deadline=deadline,
        now=current,
    )
    overview_text, overview_truncated = bound_text(overview_text)
    overview = GateDebugArtifact(
        "ok" if request.status == "ok" else "error",
        overview_text,
        overview_text,
        path=paths.root,
        truncated=overview_truncated,
    )
    return GateDebugSnapshot(
        kind=kind,
        request_id=request_id,
        notification_id=notification.id,
        icon=icon,
        status=status,
        created_at=created_at,
        age=_format_age(created_unix, current),
        bundle_path=paths.root,
        overview=overview,
        request=request,
        response=response,
        errors=errors,
        error_count=error_count,
        errors_artifact=errors_artifact,
        row=row,
        resources=resources,
    )


def _coerce_notification(value: Notification | Mapping[str, Any]) -> Notification:
    if isinstance(value, Notification):
        return value
    raw_action_data = value.get("action_data")
    action_data = raw_action_data if isinstance(raw_action_data, Mapping) else {}
    icon = value.get("icon")
    action = value.get("action")
    snooze = value.get("snooze_until")
    return Notification(
        id=str(value.get("id") or "unknown"),
        timestamp=str(value.get("timestamp") or ""),
        sender=str(value.get("sender") or "unknown"),
        icon=icon if isinstance(icon, str) else None,
        notes=_string_list(value.get("notes")),
        files=_string_list(value.get("files")),
        tags=_string_list(value.get("tags")),
        action=str(action) if action is not None else None,
        action_data={str(key): str(raw) for key, raw in action_data.items()},
        read=bool(value.get("read", False)),
        dismissed=bool(value.get("dismissed", False)),
        silent=bool(value.get("silent", False)),
        muted=bool(value.get("muted", False)),
        snooze_until=snooze if isinstance(snooze, str) else None,
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _resolve_paths(
    action: str | None, action_data: Mapping[str, str]
) -> GateDebugBundlePaths | None:
    try:
        resolved = resolve_action_bundle(action, action_data)
    except Exception:
        resolved = None
    if resolved is not None:
        return GateDebugBundlePaths(
            resolved.root,
            resolved.request,
            resolved.response,
            resolved.cancellation,
            resolved.legacy,
        )

    root_value = action_data.get("bundle_path")
    request_value = action_data.get("request_path")
    response_value = action_data.get("response_path")
    if root_value:
        root = Path(root_value).expanduser()
        return GateDebugBundlePaths(
            root,
            Path(request_value).expanduser()
            if request_value
            else root / REQUEST_FILENAME,
            Path(response_value).expanduser()
            if response_value
            else root / RESPONSE_FILENAME,
            root / CANCELLATION_FILENAME,
            False,
        )
    if request_value:
        request = Path(request_value).expanduser()
        root = request.parent
        return GateDebugBundlePaths(
            root,
            request,
            Path(response_value).expanduser()
            if response_value
            else root / RESPONSE_FILENAME,
            root / CANCELLATION_FILENAME,
            False,
        )

    request_id = action_data.get("request_id")
    adapter = adapter_for_action(action)
    request_kind = action_data.get("request_kind") or (
        adapter.kind if adapter is not None else None
    )
    if request_id and request_kind:
        try:
            neutral = bundle_paths(request_kind, request_id)
        except GateError:
            return None
        return GateDebugBundlePaths(
            neutral.root,
            neutral.request,
            neutral.response,
            neutral.cancellation,
            False,
        )
    return None


def _derive_status(
    request: GateDebugArtifact,
    terminal: GateDebugArtifact,
    *,
    terminal_kind: str | None,
    terminal_payload: Mapping[str, Any],
    deadline: float | None,
    now: float,
) -> GateDebugStatus:
    if terminal_kind is not None and terminal.status != "ok":
        return "UNKNOWN"
    if terminal_kind == "response":
        return "ANSWERED"
    if terminal_kind == "cancellation":
        return (
            "TIMED OUT" if terminal_payload.get("reason") == "timeout" else "CANCELLED"
        )
    if request.status != "ok":
        return "UNKNOWN"
    if deadline is not None and now > deadline:
        return "OVERDUE"
    return "PENDING"


def _created_time(
    envelope: Mapping[str, Any], notification_timestamp: str
) -> tuple[str | None, float | None]:
    created = envelope.get("created_at")
    created_text = created if isinstance(created, str) else None
    created_unix = _number(envelope.get("created_at_unix"))
    if created_unix is None and created_text:
        created_unix = _timestamp(created_text)
    if created_unix is None:
        created_unix = _timestamp(notification_timestamp)
    if created_text is None and created_unix is not None:
        created_text = iso_from_unix(created_unix)
    return created_text, created_unix


def _kind_for(action: str | None, action_data: Mapping[str, str]) -> str:
    value = action_data.get("request_kind")
    if value:
        return value
    adapter = adapter_for_action(action)
    return adapter.kind if adapter is not None else "notification"


def _icon_for_action(action: str | None) -> str:
    icons = {
        "PlanApproval": "📝",
        "EpicApproval": "🗺️",
        "UserQuestion": "❓",
        "LaunchApproval": "🚀",
        "CustomGate": "✨",
        "HITL": "✋",
    }
    return icons.get(action, "🔔") if action is not None else "🔔"


def _timestamp(value: str) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, OSError):
        return None


def _format_age(created: float | None, now: float) -> str:
    if created is None:
        return "unknown age"
    seconds = max(0.0, now - created)
    return f"{_format_duration(seconds)} ago"


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86_400:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    return f"{seconds // 86_400}d {seconds % 86_400 // 3600}h"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) else None


__all__ = [
    "MAX_ARTIFACT_BYTES",
    "MAX_ERROR_EXCERPT_BYTES",
    "GateDebugArtifact",
    "GateDebugContext",
    "GateDebugSnapshot",
    "build_gate_debug_snapshot",
    "debug_context_from_notification",
]
