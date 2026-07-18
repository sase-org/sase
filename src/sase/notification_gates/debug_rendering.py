"""Plain-text overview rendering for gate debug snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.notification_gates.durability import request_sha256
from sase.notifications.models import Notification


def build_gate_debug_overview(
    notification: Notification,
    *,
    kind: str,
    request_id: str,
    bundle_root: Path,
    legacy: bool,
    envelope: Mapping[str, Any],
    request_status: str,
    response_status: str,
    terminal_payload: Mapping[str, Any],
    terminal_kind: str | None,
    resources: tuple[Any, ...],
    error_count: int,
    status: str,
    created_at: str | None,
    created_unix: float | None,
    deadline: float | None,
    now: float,
) -> str:
    """Render the complete lifecycle/integrity overview as bounded-ready text."""
    producer = envelope.get("producer")
    producer_text = _producer_text(producer, fallback=notification.sender)
    lines = [
        _kv("Status", status),
        _kv("Kind", str(envelope.get("kind") or kind)),
        _kv("Request id", str(envelope.get("request_id") or request_id)),
        _kv("Notification id", notification.id),
        _kv("Sender / producer", producer_text),
        _kv("Continuation", str(envelope.get("continuation_mode") or "unknown")),
        _kv("Bundle", str(bundle_root)),
        _kv("Bundle format", "legacy" if legacy else "neutral"),
        _kv("Request integrity", _request_integrity(envelope)),
        _kv("Created", created_at or "unknown"),
        _kv("Age", _format_age(created_unix, now)),
    ]
    timeout = _number(envelope.get("gate_timeout_seconds"))
    lines.append(
        _kv("Timeout", "none" if timeout is None else _format_duration(timeout))
    )
    if deadline is not None:
        remaining = deadline - now
        lines.extend(
            (
                _kv("Deadline", _iso_from_unix(deadline)),
                _kv(
                    "Deadline state",
                    (
                        f"{_format_duration(remaining)} remaining"
                        if remaining >= 0
                        else f"{_format_duration(-remaining)} overdue"
                    ),
                ),
            )
        )
    lines.extend(_terminal_detail(terminal_payload, terminal_kind))
    lines.extend(
        (
            "",
            "Option query",
            _option_inventory(envelope),
            "",
            "Resource integrity",
            _resource_table(resources),
            "",
            "Notification / pending action",
            _kv("Read", str(notification.read).lower()),
            _kv("Dismissed", str(notification.dismissed).lower()),
            _kv("Muted", str(notification.muted).lower()),
            _kv("Snoozed until", notification.snooze_until or "no"),
            _kv("Tags", ", ".join(notification.tags) or "none"),
            _kv("Pending action", _pending_action_state(notification)),
            _kv("Request artifact", request_status),
            _kv("Terminal artifact", response_status),
            _kv("Execution errors", str(error_count)),
        )
    )
    return "\n".join(lines)


def build_no_bundle_overview(
    notification: Notification, kind: str, request_id: str
) -> str:
    """Render the explicit non-gate/missing-projection overview."""
    return "\n".join(
        (
            "No gate bundle attached to this notification.",
            "",
            _kv("Kind", kind),
            _kv("Request id", request_id),
            _kv("Notification id", notification.id),
            _kv("Sender", notification.sender),
            _kv("Action", notification.action or "none"),
            _kv("Read", str(notification.read).lower()),
            _kv("Dismissed", str(notification.dismissed).lower()),
            _kv("Muted", str(notification.muted).lower()),
            _kv("Snoozed until", notification.snooze_until or "no"),
            _kv("Tags", ", ".join(notification.tags) or "none"),
            _kv("Pending action", _pending_action_state(notification)),
        )
    )


def _request_integrity(envelope: Mapping[str, Any]) -> str:
    if not envelope:
        return "✗ request envelope is unreadable"
    hashes = envelope.get("hashes")
    expected = hashes.get("request") if isinstance(hashes, dict) else None
    if not isinstance(expected, str):
        return "⚠ expected request hash is missing"
    try:
        actual = request_sha256(dict(envelope))
    except Exception as exc:
        return f"✗ could not hash request: {exc}"
    if actual != expected:
        return f"✗ MISMATCH (expected {expected}; actual {actual})"
    return f"✓ {actual}"


def _terminal_detail(
    payload: Mapping[str, Any], terminal_kind: str | None
) -> list[str]:
    if terminal_kind == "response":
        selected = payload.get("selected_option_ids")
        options = (
            ", ".join(str(value) for value in selected)
            if isinstance(selected, list)
            else "none"
        )
        return [
            _kv("Selected options", options or "none"),
            _kv("Feedback", str(payload.get("feedback") or "none")),
            _kv("Responded", _time_field(payload, "responded_at", "responded_at_unix")),
        ]
    if terminal_kind == "cancellation":
        return [
            _kv("Cancellation reason", str(payload.get("reason") or "unknown")),
            _kv("Cancelled", _time_field(payload, "cancelled_at", "cancelled_at_unix")),
            _kv("Cancellation source", str(payload.get("source") or "unknown")),
        ]
    return [_kv("Status detail", "waiting for a terminal response")]


def _option_inventory(envelope: Mapping[str, Any]) -> str:
    options = envelope.get("options")
    if not isinstance(options, list) or not options:
        return "  ⚠ no readable options"
    raw_primary = envelope.get("primary_branch")
    if not isinstance(raw_primary, list) and envelope.get("schema_version") == 2:
        raw_branches = envelope.get("branches")
        raw_primary = (
            raw_branches[0] if isinstance(raw_branches, list) and raw_branches else None
        )
    primary = (
        ", ".join(str(option_id) for option_id in raw_primary)
        if isinstance(raw_primary, list)
        else "?"
    )
    lines = [f"  {envelope.get('query') or '?'}", f"  Primary: {primary}"]
    for value in options:
        if not isinstance(value, dict):
            lines.append("  ✗ invalid option declaration")
            continue
        command = value.get("command")
        argv = command.get("argv") if isinstance(command, dict) else None
        lines.append(
            "  {icon} {id}: {label} | default={default} | feedback={feedback} | argv={argv}".format(
                icon=value.get("icon") or "•",
                id=value.get("id") or "?",
                label=value.get("label") or "?",
                default=str(value.get("default_selected", True)).lower(),
                feedback=value.get("feedback") or "disabled",
                argv=" ".join(str(item) for item in argv)
                if isinstance(argv, list)
                else "?",
            )
        )
    return "\n".join(lines)


def _resource_table(resources: tuple[Any, ...]) -> str:
    if not resources:
        return "  (none declared or request unreadable)"
    lines = ["  state  size       mode  role        path"]
    glyphs = {"ok": "✓", "mismatch": "✗", "missing": "⚠", "error": "✗"}
    for resource in resources:
        size = _format_size(resource.size)
        mode = "exec" if resource.executable else "file"
        lines.append(
            f"  {glyphs[resource.integrity]:<5}  {size:<9}  {mode:<4}  "
            f"{resource.role:<10}  {resource.path}"
        )
        if resource.integrity != "ok":
            lines.append(f"         {resource.detail}")
    return "\n".join(lines)


def _pending_action_state(notification: Notification) -> str:
    try:
        from sase.notifications.pending_actions import (
            action_state_for_notification,
            read_pending_action_store,
        )

        store = read_pending_action_store(include_legacy=True)
        state = action_state_for_notification(notification, store=store)
        actions = store.get("actions", {})
        entry = next(
            (
                value
                for value in actions.values()
                if isinstance(value, dict)
                and value.get("notification_id") == notification.id
            ),
            None,
        )
        if isinstance(entry, dict):
            stale = entry.get("stale_deadline_unix")
            transports = entry.get("transports")
            transport_names = [
                str(item.get("transport"))
                for item in transports or []
                if isinstance(item, dict) and item.get("transport")
            ]
            detail = state
            if isinstance(stale, (int, float)):
                detail += f"; stale deadline {_iso_from_unix(float(stale))}"
            if transport_names:
                detail += f"; transports {', '.join(transport_names)}"
            return detail
        return f"{state}; registration missing"
    except Exception as exc:
        return f"unreadable ({exc})"


def _producer_text(value: object, *, fallback: str) -> str:
    if not isinstance(value, Mapping) or not value:
        return fallback
    agent = value.get("agent") or value.get("agent_name") or value.get("name")
    machine = value.get("machine") or value.get("hostname")
    parts = [str(part) for part in (agent, machine) if part]
    return " @ ".join(parts) if parts else json.dumps(dict(value), ensure_ascii=False)


def _time_field(payload: Mapping[str, Any], text_key: str, unix_key: str) -> str:
    value = payload.get(text_key)
    if isinstance(value, str):
        return value
    unix = _number(payload.get(unix_key))
    return _iso_from_unix(unix) if unix is not None else "unknown"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _format_age(created: float | None, now: float) -> str:
    if created is None:
        return "unknown age"
    return f"{_format_duration(max(0.0, now - created))} ago"


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86_400:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    return f"{seconds // 86_400}d {seconds % 86_400 // 3600}h"


def _format_size(size: int | None) -> str:
    if size is None:
        return "—"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _iso_from_unix(value: float) -> str:
    try:
        return datetime.fromtimestamp(value).astimezone().isoformat()
    except (ValueError, OSError, OverflowError):
        return str(value)


def _kv(label: str, value: str) -> str:
    return f"{label:<19} {value}"


__all__ = ["build_gate_debug_overview", "build_no_bundle_overview"]
