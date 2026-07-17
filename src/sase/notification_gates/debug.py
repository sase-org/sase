"""Best-effort, bounded diagnostics for notification gate bundles."""

from __future__ import annotations

import dataclasses
import heapq
import json
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from sase.notification_gates.debug_rendering import (
    build_gate_debug_overview,
    build_no_bundle_overview,
)
from sase.notification_gates.durability import sha256_file, verify_mode
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    REQUEST_FILENAME,
    RESPONSE_FILENAME,
    bundle_paths,
    owned_resource_path,
    resolve_action_bundle,
)
from sase.notification_gates.registry import adapter_for_action
from sase.notifications.models import Notification

MAX_ARTIFACT_BYTES = 256 * 1024
MAX_ERROR_EXCERPT_BYTES = 16 * 1024
MAX_ERROR_RECORDS = 50
_TRUNCATION_BANNER = "\n\n--- truncated after {limit} bytes ---"

ArtifactStatus = Literal["ok", "missing", "error"]
GateDebugStatus = Literal[
    "PENDING",
    "ANSWERED",
    "CANCELLED",
    "TIMED OUT",
    "OVERDUE",
    "UNKNOWN",
]


@dataclass(frozen=True)
class GateDebugContext:
    """Stable in-hand input used to open a gate debug surface immediately."""

    notification: Notification
    action_data: Mapping[str, str]


@dataclass(frozen=True)
class GateDebugArtifact:
    """One bounded artifact rendered by a debug tab."""

    status: ArtifactStatus
    body: str
    raw_text: str
    path: Path | None = None
    error: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class _GateDebugResource:
    """Live integrity result for one reviewed bundle resource."""

    path: str
    role: str
    executable: bool
    size: int | None
    integrity: Literal["ok", "mismatch", "missing", "error"]
    detail: str


@dataclass(frozen=True)
class _GateDebugError:
    """One execution-error record from the bundle's errors directory."""

    path: Path
    code: str
    message: str
    source: str
    returncode: int | None
    stdout: str | None
    stderr: str | None
    body: str


@dataclass(frozen=True)
class GateDebugSnapshot:
    """Complete, immutable debug projection for a notification gate."""

    kind: str
    request_id: str
    notification_id: str
    icon: str
    status: GateDebugStatus
    created_at: str | None
    age: str
    bundle_path: Path | None
    overview: GateDebugArtifact
    request: GateDebugArtifact
    response: GateDebugArtifact
    errors: tuple[_GateDebugError, ...]
    error_count: int
    errors_artifact: GateDebugArtifact
    row: GateDebugArtifact
    resources: tuple[_GateDebugResource, ...]


@dataclass(frozen=True)
class _ResolvedPaths:
    root: Path
    request: Path
    response: Path
    cancellation: Path
    legacy: bool


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
        row = _notification_row_artifact(notification)
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

    request = _read_json_artifact(paths.request, label=paths.request.name)
    envelope = _parsed_json(request)
    kind = str(envelope.get("kind") or kind) if envelope else kind
    request_id = (
        str(envelope.get("request_id") or request_id) if envelope else request_id
    )
    response, terminal_payload, terminal_kind = _terminal_artifact(paths)
    errors, error_count, errors_artifact = _error_artifacts(paths.root / "errors")
    resources = _resource_integrity(paths.root, envelope)
    row = _notification_row_artifact(notification)

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
    overview_text, overview_truncated = _bound_text(overview_text)
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
) -> _ResolvedPaths | None:
    try:
        resolved = resolve_action_bundle(action, action_data)
    except Exception:
        resolved = None
    if resolved is not None:
        return _ResolvedPaths(
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
        return _ResolvedPaths(
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
        return _ResolvedPaths(
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
        return _ResolvedPaths(
            neutral.root,
            neutral.request,
            neutral.response,
            neutral.cancellation,
            False,
        )
    return None


def _bounded_read(path: Path, *, limit: int = MAX_ARTIFACT_BYTES) -> tuple[str, bool]:
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    truncated = len(value) > limit
    if truncated:
        value = value[:limit]
    text = value.decode("utf-8", errors="replace")
    if truncated:
        text += _TRUNCATION_BANNER.format(limit=limit)
    return text, truncated


def _read_json_artifact(path: Path, *, label: str) -> GateDebugArtifact:
    try:
        raw, truncated = _bounded_read(path)
    except FileNotFoundError:
        body = f"⚠ {label} is missing: {path}"
        return GateDebugArtifact("missing", body, body, path=path)
    except Exception as exc:
        body = f"✗ {label}: {exc}"
        return GateDebugArtifact("error", body, body, path=path, error=str(exc))
    if truncated:
        body = f"✗ {label}: artifact exceeds the bounded read limit\n\n{raw}"
        return GateDebugArtifact(
            "error",
            body,
            raw,
            path=path,
            error="artifact was truncated before JSON parsing",
            truncated=True,
        )
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("top-level JSON value is not an object")
    except Exception as exc:
        body = f"✗ {label}: {exc}\n\n{raw}"
        return GateDebugArtifact("error", body, raw, path=path, error=str(exc))
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=False)
    body, pretty_truncated = _bound_text(pretty)
    return GateDebugArtifact("ok", body, raw, path=path, truncated=pretty_truncated)


def _parsed_json(artifact: GateDebugArtifact) -> dict[str, Any]:
    if artifact.status != "ok":
        return {}
    try:
        value = json.loads(artifact.raw_text)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _terminal_artifact(
    paths: _ResolvedPaths,
) -> tuple[GateDebugArtifact, dict[str, Any], str | None]:
    if paths.response.exists() or paths.response.is_symlink():
        artifact = _read_json_artifact(paths.response, label=paths.response.name)
        return artifact, _parsed_json(artifact), "response"
    if paths.cancellation.exists() or paths.cancellation.is_symlink():
        artifact = _read_json_artifact(
            paths.cancellation, label=paths.cancellation.name
        )
        return artifact, _parsed_json(artifact), "cancellation"
    body = (
        "Pending — no response has been written yet.\n\n"
        f"A response will appear at:\n{paths.response}\n\n"
        f"A cancellation will appear at:\n{paths.cancellation}"
    )
    return GateDebugArtifact("missing", body, body, path=paths.response), {}, None


def _error_artifacts(
    directory: Path,
) -> tuple[tuple[_GateDebugError, ...], int, GateDebugArtifact]:
    try:
        newest: list[tuple[str, Path]] = []
        count = 0
        for path in directory.iterdir():
            if not path.name.endswith(".json"):
                continue
            count += 1
            heapq.heappush(newest, (path.name, path))
            if len(newest) > MAX_ERROR_RECORDS:
                heapq.heappop(newest)
        paths = [path for _name, path in sorted(newest, reverse=True)]
    except FileNotFoundError:
        text = "No gate execution errors recorded."
        return (), 0, GateDebugArtifact("missing", text, text, path=directory)
    except Exception as exc:
        text = f"✗ Could not list {directory}: {exc}"
        return (
            (),
            0,
            GateDebugArtifact("error", text, text, path=directory, error=str(exc)),
        )

    omitted = max(0, count - len(paths))
    records: list[_GateDebugError] = []
    bodies: list[str] = []
    for path in paths:
        artifact = _read_json_artifact(path, label=path.name)
        payload = _parsed_json(artifact)
        stdout = _bounded_excerpt(payload.get("stdout"))
        stderr = _bounded_excerpt(payload.get("stderr"))
        returncode = payload.get("returncode")
        if not isinstance(returncode, int):
            returncode = None
        code = str(payload.get("code") or "unreadable")
        message = str(payload.get("message") or artifact.error or "")
        source = str(payload.get("source") or "unknown")
        lines = [
            f"✗ {path.name}",
            f"  code: {code}",
            f"  message: {message or '(none)'}",
            f"  source: {source}",
            f"  returncode: {returncode if returncode is not None else '(none)'}",
        ]
        if stdout:
            lines.extend(("  stdout:", _indent(stdout, "    ")))
        if stderr:
            lines.extend(("  stderr:", _indent(stderr, "    ")))
        if artifact.status != "ok":
            lines.extend(("  raw diagnostic:", _indent(artifact.body, "    ")))
        body = "\n".join(lines)
        bodies.append(body)
        records.append(
            _GateDebugError(
                path=path,
                code=code,
                message=message,
                source=source,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                body=body,
            )
        )
    if omitted:
        bodies.append(f"⚠ {omitted} older error record(s) omitted.")
    text = "\n\n".join(bodies) if bodies else "No gate execution errors recorded."
    text, truncated = _bound_text(text)
    status: ArtifactStatus = "ok" if records else "missing"
    return (
        tuple(records),
        count,
        GateDebugArtifact(status, text, text, path=directory, truncated=truncated),
    )


def _bounded_excerpt(value: object) -> str | None:
    if value is None:
        return None
    raw = str(value).encode("utf-8", errors="replace")
    truncated = len(raw) > MAX_ERROR_EXCERPT_BYTES
    raw = raw[:MAX_ERROR_EXCERPT_BYTES]
    text = raw.decode("utf-8", errors="replace")
    if truncated:
        text += _TRUNCATION_BANNER.format(limit=MAX_ERROR_EXCERPT_BYTES)
    return text


def _resource_integrity(
    root: Path, envelope: Mapping[str, Any]
) -> tuple[_GateDebugResource, ...]:
    raw_resources = envelope.get("resources")
    hashes = envelope.get("hashes")
    expected_resources = hashes.get("resources") if isinstance(hashes, dict) else {}
    if not isinstance(raw_resources, list):
        return ()
    if not isinstance(expected_resources, dict):
        expected_resources = {}
    results: list[_GateDebugResource] = []
    for index, value in enumerate(raw_resources):
        if not isinstance(value, dict):
            results.append(
                _GateDebugResource(
                    f"resources[{index}]",
                    "unknown",
                    False,
                    None,
                    "error",
                    "resource declaration is not an object",
                )
            )
            continue
        relative = value.get("path")
        role = str(value.get("role") or "attachment")
        executable = value.get("executable", False)
        if not isinstance(relative, str) or not isinstance(executable, bool):
            results.append(
                _GateDebugResource(
                    str(relative or f"resources[{index}]"),
                    role,
                    bool(executable),
                    None,
                    "error",
                    "invalid path or executable declaration",
                )
            )
            continue
        try:
            path = owned_resource_path(root, relative)
        except Exception as exc:
            results.append(
                _GateDebugResource(relative, role, executable, None, "error", str(exc))
            )
            continue
        expected = expected_resources.get(relative)
        try:
            size = path.stat().st_size
            verify_mode(path, executable=executable)
            actual = sha256_file(path)
        except FileNotFoundError:
            results.append(
                _GateDebugResource(
                    relative, role, executable, None, "missing", "resource is missing"
                )
            )
            continue
        except Exception as exc:
            results.append(
                _GateDebugResource(relative, role, executable, None, "error", str(exc))
            )
            continue
        if not isinstance(expected, str):
            results.append(
                _GateDebugResource(
                    relative,
                    role,
                    executable,
                    size,
                    "error",
                    f"no expected hash; actual {actual}",
                )
            )
        elif actual != expected:
            results.append(
                _GateDebugResource(
                    relative,
                    role,
                    executable,
                    size,
                    "mismatch",
                    f"expected {expected}; actual {actual}",
                )
            )
        else:
            results.append(
                _GateDebugResource(
                    relative, role, executable, size, "ok", f"sha256 {actual}"
                )
            )
    return tuple(results)


def _notification_row_artifact(notification: Notification) -> GateDebugArtifact:
    fallback = dataclasses.asdict(notification)
    path: Path | None = None
    try:
        from sase.notifications.store import notifications_file_path

        path = notifications_file_path()
        with path.open("rb") as stream:
            while True:
                raw_line = stream.readline(MAX_ARTIFACT_BYTES + 1)
                if not raw_line:
                    break
                complete = (
                    raw_line.endswith(b"\n") or len(raw_line) <= MAX_ARTIFACT_BYTES
                )
                if not complete:
                    _discard_line_remainder(stream)
                    continue
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                try:
                    value = json.loads(line)
                except Exception:
                    continue
                if isinstance(value, dict) and value.get("id") == notification.id:
                    pretty, truncated = _bound_text(
                        json.dumps(value, indent=2, ensure_ascii=False)
                    )
                    return GateDebugArtifact(
                        "ok",
                        pretty,
                        line,
                        path=path,
                        truncated=truncated,
                    )
    except Exception:
        pass
    raw = json.dumps(fallback, ensure_ascii=False)
    text, truncated = _bound_text(json.dumps(fallback, indent=2, ensure_ascii=False))
    raw, _raw_truncated = _bound_text(raw)
    return GateDebugArtifact("ok", text, raw, path=path, truncated=truncated)


def _discard_line_remainder(stream: Any) -> None:
    """Advance past one oversized JSONL row without retaining its bytes."""
    while True:
        chunk = stream.readline(MAX_ARTIFACT_BYTES)
        if not chunk or chunk.endswith(b"\n"):
            return


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
        created_text = _iso_from_unix(created_unix)
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


def _iso_from_unix(value: float) -> str:
    try:
        return datetime.fromtimestamp(value).astimezone().isoformat()
    except (ValueError, OSError, OverflowError):
        return str(value)


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


def _bound_text(value: str, *, limit: int = MAX_ARTIFACT_BYTES) -> tuple[str, bool]:
    raw = value.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return value, False
    bounded = raw[:limit].decode("utf-8", errors="replace")
    return bounded + _TRUNCATION_BANNER.format(limit=limit), True


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _indent(value: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in value.splitlines())


__all__ = [
    "MAX_ARTIFACT_BYTES",
    "MAX_ERROR_EXCERPT_BYTES",
    "GateDebugArtifact",
    "GateDebugContext",
    "GateDebugSnapshot",
    "build_gate_debug_snapshot",
    "debug_context_from_notification",
]
