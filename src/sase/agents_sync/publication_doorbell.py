"""Machine-local doorbell, hint journal, and liveness heartbeat for publication."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import datetime
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any
import uuid

from sase.agents_sync.io import atomic_write_json
from sase.core.paths import (
    sase_home,
    sase_projects_dir,
    validate_sase_project_name,
)

_HINTS_FILENAME = "hints.jsonl"
_CLAIM_PREFIX = "hints.claimed."
_HEARTBEAT_FILENAME = "heartbeat.json"
_HEARTBEAT_SCHEMA_VERSION = 1
_HINT_FIELDS = (
    "local_agent",
    "global_agent",
    "primary_revision",
    "run_id",
    "link_outbox_agent_name",
)


@dataclass(frozen=True, slots=True)
class PublicationHintClaim:
    """Hints moved aside for one publication pass.

    Claimed files deliberately remain on disk until :func:`finish_hint_claim`
    succeeds. If a publisher dies, the next pass reads the same files again.
    """

    project_key: str
    paths: tuple[Path, ...]
    hints: tuple[dict[str, Any], ...]


def _project_publication_dir(project_key: str) -> Path:
    """Return the validated machine-owned publication directory for a project."""

    validate_sase_project_name(project_key)
    return sase_projects_dir() / project_key / "agent_publication"


def _publication_heartbeat_path() -> Path:
    """Return the machine-wide publisher heartbeat path."""

    return sase_home() / "agent_publication" / _HEARTBEAT_FILENAME


def ring_publication_doorbell(
    project_key: str,
    hint: Mapping[str, object] | None = None,
) -> Path:
    """Append an optional non-authoritative hint and atomically ring the bell."""

    directory = _project_publication_dir(project_key)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if hint is not None:
        _append_hint(directory / _HINTS_FILENAME, hint)
    return _ring_project_directory(directory)


def append_publication_hint(
    project_key: str,
    hint: Mapping[str, object],
) -> Path:
    """Append a durable hint without waking the publisher yet."""

    directory = _project_publication_dir(project_key)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / _HINTS_FILENAME
    _append_hint(path, hint)
    return path


def _ring_project_directory(directory: Path) -> Path:
    """Atomically touch the doorbell under a validated project directory."""

    doorbell = directory / "doorbell"
    fd, raw_tmp = tempfile.mkstemp(prefix=".doorbell.", dir=directory)
    temp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"publication\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, doorbell)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    return doorbell


def claim_publication_hints(project_key: str) -> PublicationHintClaim:
    """Atomically claim new hints and include claims left by an interrupted pass."""

    directory = _project_publication_dir(project_key)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    hints_path = directory / _HINTS_FILENAME
    claims = sorted(directory.glob(f"{_CLAIM_PREFIX}*.jsonl"))
    if hints_path.exists():
        claimed = directory / f"{_CLAIM_PREFIX}{os.getpid()}.{uuid.uuid4().hex}.jsonl"
        try:
            os.replace(hints_path, claimed)
        except FileNotFoundError:
            pass
        else:
            claims.append(claimed)
    claims = sorted(set(claims))
    hints: list[dict[str, Any]] = []
    for path in claims:
        hints.extend(_read_hints(path))
    return PublicationHintClaim(project_key, tuple(claims), tuple(hints))


def finish_hint_claim(claim: PublicationHintClaim) -> None:
    """Remove claimed hints after the pass has handled them."""

    for path in claim.paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue


def write_publication_heartbeat(
    projects: Mapping[str, Mapping[str, object]],
    *,
    now: float | None = None,
) -> Path:
    """Atomically write per-project queue statistics for publisher liveness."""

    timestamp = float(time.time() if now is None else now)
    payload = {
        "schema_version": _HEARTBEAT_SCHEMA_VERSION,
        "updated_at": timestamp,
        "updated_at_utc": datetime.datetime.fromtimestamp(
            timestamp, datetime.UTC
        ).isoformat(),
        "projects": {key: dict(value) for key, value in sorted(projects.items())},
    }
    path = _publication_heartbeat_path()
    atomic_write_json(path, payload)
    return path


def _read_publication_heartbeat() -> dict[str, Any] | None:
    """Read a valid heartbeat payload, returning ``None`` when absent or invalid."""

    path = _publication_heartbeat_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _HEARTBEAT_SCHEMA_VERSION
        or not isinstance(payload.get("updated_at"), (int, float))
        or not isinstance(payload.get("projects"), dict)
    ):
        return None
    return payload


def publisher_is_live(max_age_seconds: float) -> bool:
    """Return whether a valid publisher heartbeat is newer than the age limit."""

    if max_age_seconds <= 0:
        return False
    payload = _read_publication_heartbeat()
    if payload is None:
        return False
    age = time.time() - float(payload["updated_at"])
    return 0 <= age <= max_age_seconds


def _append_hint(path: Path, hint: Mapping[str, object]) -> None:
    normalized: dict[str, object] = {}
    for field in _HINT_FIELDS:
        value = hint.get(field)
        if not isinstance(value, str):
            raise ValueError(f"publication hint {field} must be a string")
        normalized[field] = value
    normalized["created_at"] = float(time.time())
    line = (
        json.dumps(
            normalized, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        + b"\n"
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_hints(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    hints: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict) or any(
            not isinstance(value.get(field), str) for field in _HINT_FIELDS
        ):
            continue
        hints.append(value)
    return hints


__all__ = [
    "PublicationHintClaim",
    "append_publication_hint",
    "claim_publication_hints",
    "finish_hint_claim",
    "publisher_is_live",
    "ring_publication_doorbell",
    "write_publication_heartbeat",
]
