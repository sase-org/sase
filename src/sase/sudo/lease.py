"""Host-wide sudo authentication lease."""

from __future__ import annotations

import getpass
import os
import socket
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir
from sase.notification_gates.durability import atomic_write_json, file_lock, fsync_dir
from sase.notification_gates.models import GateError

_LOCK_NAME = "sudo-auth.lock"
_STATE_NAME = "sudo-auth.json"


def _sudo_auth_lock_path() -> Path:
    """Return the host-wide sudo authentication lock path."""
    return sase_subdir("locks") / _LOCK_NAME


def _sudo_auth_state_path() -> Path:
    """Return the non-secret metadata path for the active sudo auth lease."""
    return sase_subdir("locks") / _STATE_NAME


@contextmanager
def sudo_auth_lease(
    *,
    request_id: str,
    run_as: str,
    cwd: str,
    command_ids: Sequence[str],
) -> Iterator[None]:
    """Acquire a non-blocking single-active sudo authentication lease."""
    owner_id = uuid.uuid4().hex
    lock_path = _sudo_auth_lock_path()
    state_path = _sudo_auth_state_path()
    try:
        with file_lock(lock_path, timeout=0.0):
            atomic_write_json(
                state_path,
                _lease_state(
                    owner_id=owner_id,
                    request_id=request_id,
                    run_as=run_as,
                    cwd=cwd,
                    command_count=len(command_ids),
                ),
            )
            try:
                yield
            finally:
                _release_state(state_path, owner_id=owner_id)
    except GateError as exc:
        if exc.code != "lock_timeout":
            raise
        raise GateError(
            "auth_lease_busy",
            "sudo_auth_lease",
            _contention_message(state_path),
        ) from exc


def _lease_state(
    *,
    owner_id: str,
    request_id: str,
    run_as: str,
    cwd: str,
    command_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "owner_id": owner_id,
        "request_id": request_id,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "user": getpass.getuser(),
        "run_as": run_as,
        "cwd": cwd,
        "command_count": command_count,
        "started_at": datetime.now(UTC).isoformat(),
    }


def _release_state(path: Path, *, owner_id: str) -> None:
    try:
        current = _read_state(path)
    except OSError:
        current = None
    if current is not None and current.get("owner_id") != owner_id:
        return
    try:
        path.unlink(missing_ok=True)
        fsync_dir(path.parent)
    except OSError:
        pass


def _read_state(path: Path) -> Mapping[str, Any] | None:
    try:
        value = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    import json

    decoded = json.loads(value)
    return decoded if isinstance(decoded, Mapping) else None


def _contention_message(path: Path) -> str:
    try:
        state = _read_state(path)
    except (OSError, ValueError):
        state = None
    if state is None:
        return "another sudo authentication handoff is already active"
    request_id = _state_text(state, "request_id", "unknown request")
    host = _state_text(state, "host", "unknown host")
    pid = _state_text(state, "pid", "unknown pid")
    user = _state_text(state, "user", "unknown user")
    run_as = _state_text(state, "run_as", "root")
    started = _state_text(state, "started_at", "unknown time")
    command_count = _state_text(state, "command_count", "unknown command count")
    return (
        "another sudo authentication handoff is already active "
        f"for {request_id} on {host} as {user} "
        f"(pid {pid}, run-as {run_as}, commands {command_count}, started {started})"
    )


def _state_text(state: Mapping[str, Any], key: str, default: str) -> str:
    value = state.get(key)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


__all__ = [
    "sudo_auth_lease",
]
