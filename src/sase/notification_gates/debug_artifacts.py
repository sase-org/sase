"""Bounded artifact collection for notification gate diagnostics."""

from __future__ import annotations

import dataclasses
import heapq
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.notification_gates.debug_models import (
    ArtifactStatus,
    GateDebugArtifact,
    GateDebugBundlePaths,
    GateDebugError,
    GateDebugResource,
)
from sase.notification_gates.durability import sha256_file, verify_mode
from sase.notification_gates.paths import owned_resource_path
from sase.notifications.models import Notification

MAX_ARTIFACT_BYTES = 256 * 1024
MAX_ERROR_EXCERPT_BYTES = 16 * 1024
MAX_ERROR_RECORDS = 50
_TRUNCATION_BANNER = "\n\n--- truncated after {limit} bytes ---"


def read_json_artifact(path: Path, *, label: str) -> GateDebugArtifact:
    """Read and format one bounded JSON object artifact."""
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
    body, pretty_truncated = bound_text(pretty)
    return GateDebugArtifact("ok", body, raw, path=path, truncated=pretty_truncated)


def parsed_json(artifact: GateDebugArtifact) -> dict[str, Any]:
    """Return the object encoded by a valid JSON artifact, if any."""
    if artifact.status != "ok":
        return {}
    try:
        value = json.loads(artifact.raw_text)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def terminal_artifact(
    paths: GateDebugBundlePaths,
) -> tuple[GateDebugArtifact, dict[str, Any], str | None]:
    """Read the response or cancellation artifact for a gate bundle."""
    if paths.response.exists() or paths.response.is_symlink():
        artifact = read_json_artifact(paths.response, label=paths.response.name)
        return artifact, parsed_json(artifact), "response"
    if paths.cancellation.exists() or paths.cancellation.is_symlink():
        artifact = read_json_artifact(paths.cancellation, label=paths.cancellation.name)
        return artifact, parsed_json(artifact), "cancellation"
    body = (
        "Pending — no response has been written yet.\n\n"
        f"A response will appear at:\n{paths.response}\n\n"
        f"A cancellation will appear at:\n{paths.cancellation}"
    )
    return GateDebugArtifact("missing", body, body, path=paths.response), {}, None


def error_artifacts(
    directory: Path,
) -> tuple[tuple[GateDebugError, ...], int, GateDebugArtifact]:
    """Collect the newest bounded execution-error records."""
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
    records: list[GateDebugError] = []
    bodies: list[str] = []
    for path in paths:
        artifact = read_json_artifact(path, label=path.name)
        payload = parsed_json(artifact)
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
            GateDebugError(
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
    text, truncated = bound_text(text)
    status: ArtifactStatus = "ok" if records else "missing"
    return (
        tuple(records),
        count,
        GateDebugArtifact(status, text, text, path=directory, truncated=truncated),
    )


def resource_integrity(
    root: Path, envelope: Mapping[str, Any]
) -> tuple[GateDebugResource, ...]:
    """Verify the size, mode, and hash of every declared resource."""
    raw_resources = envelope.get("resources")
    hashes = envelope.get("hashes")
    expected_resources = hashes.get("resources") if isinstance(hashes, dict) else {}
    if not isinstance(raw_resources, list):
        return ()
    if not isinstance(expected_resources, dict):
        expected_resources = {}
    results: list[GateDebugResource] = []
    for index, value in enumerate(raw_resources):
        if not isinstance(value, dict):
            results.append(
                GateDebugResource(
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
                GateDebugResource(
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
                GateDebugResource(relative, role, executable, None, "error", str(exc))
            )
            continue
        expected = expected_resources.get(relative)
        try:
            size = path.stat().st_size
            verify_mode(path, executable=executable)
            actual = sha256_file(path)
        except FileNotFoundError:
            results.append(
                GateDebugResource(
                    relative, role, executable, None, "missing", "resource is missing"
                )
            )
            continue
        except Exception as exc:
            results.append(
                GateDebugResource(relative, role, executable, None, "error", str(exc))
            )
            continue
        if not isinstance(expected, str):
            results.append(
                GateDebugResource(
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
                GateDebugResource(
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
                GateDebugResource(
                    relative, role, executable, size, "ok", f"sha256 {actual}"
                )
            )
    return tuple(results)


def notification_row_artifact(notification: Notification) -> GateDebugArtifact:
    """Read a notification's source JSONL row, falling back to the model."""
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
                    pretty, truncated = bound_text(
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
    text, truncated = bound_text(json.dumps(fallback, indent=2, ensure_ascii=False))
    raw, _raw_truncated = bound_text(raw)
    return GateDebugArtifact("ok", text, raw, path=path, truncated=truncated)


def bound_text(value: str, *, limit: int = MAX_ARTIFACT_BYTES) -> tuple[str, bool]:
    """Bound UTF-8 text to the debug artifact size limit."""
    raw = value.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return value, False
    bounded = raw[:limit].decode("utf-8", errors="replace")
    return bounded + _TRUNCATION_BANNER.format(limit=limit), True


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


def _discard_line_remainder(stream: Any) -> None:
    """Advance past one oversized JSONL row without retaining its bytes."""
    while True:
        chunk = stream.readline(MAX_ARTIFACT_BYTES)
        if not chunk or chunk.endswith(b"\n"):
            return


def _indent(value: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in value.splitlines())
