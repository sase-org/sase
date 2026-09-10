"""Durable host-owned retry state for unpublished artifact-link sidecar commits."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
import errno
import fcntl
import json
import os
import tempfile
import time

from sase.core.artifact_link_publication_retry import (
    artifact_link_publication_mark_attempt,
    artifact_link_publication_register_pending,
    artifact_link_publication_state_wire_schema_version,
)
from sase.core.paths import sase_projects_dir
from sase.sdd._artifact_link_machine_store import MachineArtifactLinkRoot
from sase.sdd._artifact_link_publication_retry_support import (
    bounded_timeout,
    publication_observation,
)

_STATE_FILENAME = "artifact_link_publications.json"
_LOCK_FILENAME = "artifact_link_publications.lock"
_NEXT_ROLE_FIELD = "next_role"
_STATE_LOCK_TIMEOUT_SECONDS = 2.0


class _ArtifactLinkPublicationStateBusy(RuntimeError):
    """Raised when retry state is locked by another process."""


def register_pending(
    root: MachineArtifactLinkRoot,
    now: float,
    *,
    observation: dict[str, Any] | None = None,
    deadline: float | None = None,
) -> tuple[dict[str, Any] | None, str | None, bool]:
    if observation is None:
        observation, diagnostic = publication_observation(root, now, deadline=deadline)
        if observation is None:
            return None, diagnostic, False
    key = str(observation["key"])
    payload = {item: value for item, value in observation.items() if item != "key"}
    path = _artifact_link_publication_state_path(root.project_key)
    with _state_lock(path, deadline=deadline):
        records, next_role = _read_state_unlocked(path)
        current = records.get(key)
        try:
            record = artifact_link_publication_register_pending(
                current if isinstance(current, dict) else None,
                payload,
                now=now,
            )
        except Exception:
            record = artifact_link_publication_register_pending(
                None,
                payload,
                now=now,
            )
        discovered = key not in records
        records[key] = record
        _write_state_unlocked(path, records, next_role)
    return record, None, discovered


def mark_attempt(
    project_key: str,
    record: dict[str, Any],
    attempt: dict[str, Any],
    now: float,
    *,
    deadline: float | None = None,
) -> dict[str, Any]:
    key = str(record["key"])
    path = _artifact_link_publication_state_path(project_key)
    with _state_lock(path, deadline=deadline):
        records, next_role = _read_state_unlocked(path)
        current = records.get(key)
        base = current if isinstance(current, dict) else record
        marked = artifact_link_publication_mark_attempt(base, attempt, now=now)
        records[key] = marked
        _write_state_unlocked(path, records, next_role)
    return marked


def clear_record(project_key: str, key: str, *, deadline: float | None = None) -> bool:
    path = _artifact_link_publication_state_path(project_key)
    with _state_lock(path, deadline=deadline):
        records, next_role = _read_state_unlocked(path)
        if key not in records:
            return False
        del records[key]
        _write_state_unlocked(path, records, next_role)
    return True


def rotate_retry_roots(
    roots: tuple[MachineArtifactLinkRoot, ...], *, deadline: float | None
) -> tuple[MachineArtifactLinkRoot, ...]:
    if len(roots) < 2:
        return roots
    projects = {root.project_key for root in roots}
    if len(projects) != 1:
        return roots
    project_key = roots[0].project_key
    try:
        next_role = _read_next_retry_role(project_key, deadline=deadline)
    except Exception:
        return roots
    if next_role is None:
        return roots
    for index, root in enumerate(roots):
        if root.role == next_role:
            return (*roots[index:], *roots[:index])
    return roots


def _read_next_retry_role(
    project_key: str, *, deadline: float | None = None
) -> str | None:
    path = _artifact_link_publication_state_path(project_key)
    with _state_lock(path, deadline=deadline):
        _records, next_role = _read_state_unlocked(path)
    return next_role


def write_next_retry_role(
    project_key: str,
    next_role: str | None,
    *,
    deadline: float | None = None,
) -> None:
    path = _artifact_link_publication_state_path(project_key)
    with _state_lock(path, deadline=deadline):
        records, _old_next_role = _read_state_unlocked(path)
        _write_state_unlocked(path, records, next_role)


def next_retry_role_after(
    roots: tuple[MachineArtifactLinkRoot, ...],
    last_started: MachineArtifactLinkRoot,
) -> str | None:
    project_roots = [
        root for root in roots if root.project_key == last_started.project_key
    ]
    if not project_roots:
        return None
    for index, root in enumerate(project_roots):
        if root.role == last_started.role:
            return project_roots[(index + 1) % len(project_roots)].role
    return project_roots[0].role


def _artifact_link_publication_state_path(project_key: str) -> Path:
    """Return the host-owned publication retry state file for *project_key*."""

    key = project_key.strip()
    if not key or "/" in key or key in {".", ".."}:
        raise ValueError(
            f"invalid project key for artifact-link publication state: {project_key!r}"
        )
    return sase_projects_dir() / key / _STATE_FILENAME


def _read_state_unlocked(path: Path) -> tuple[dict[str, dict[str, Any]], str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version")
        != artifact_link_publication_state_wire_schema_version()
    ):
        return {}, None
    records = payload.get("records")
    if not isinstance(records, dict):
        records = {}
    next_role = payload.get(_NEXT_ROLE_FIELD)
    return (
        {
            str(key): value
            for key, value in records.items()
            if isinstance(key, str) and isinstance(value, dict)
        },
        next_role if isinstance(next_role, str) and next_role else None,
    )


def _write_state_unlocked(
    path: Path,
    records: dict[str, dict[str, Any]],
    next_role: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": artifact_link_publication_state_wire_schema_version(),
        "records": records,
    }
    if next_role:
        payload[_NEXT_ROLE_FIELD] = next_role
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


@contextmanager
def _state_lock(path: Path, *, deadline: float | None = None) -> Iterator[None]:
    lock_path = path.with_name(_LOCK_FILENAME)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        _flock_with_timeout(
            lock_file.fileno(),
            bounded_timeout(_STATE_LOCK_TIMEOUT_SECONDS, deadline),
        )
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _flock_with_timeout(fd: int, timeout_seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            if time.monotonic() >= deadline:
                raise _ArtifactLinkPublicationStateBusy(
                    "artifact-link publication retry state is locked"
                ) from exc
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
