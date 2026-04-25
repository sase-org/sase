"""Sidecar idempotency markers for mentors-complete notifications.

Tracks which (project_file, changespec_name, entry_id) tuples have already
received a mentors-complete notification, so the polling loop in
``mentor_checks`` doesn't re-emit on every cycle. Lives outside the
ChangeSpec ``.gp`` files so it survives archival without polluting display.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime
from pathlib import Path

from sase.core.time import get_timezone


def _marker_dir() -> str:
    return os.path.expanduser("~/.sase/notifications")


def _marker_file() -> str:
    return os.path.join(_marker_dir(), "mentors_complete.json")


def _key(project_file: str, changespec_name: str, entry_id: str) -> str:
    return f"{project_file}::{changespec_name}::{entry_id}"


def _load() -> dict[str, str]:
    path = Path(_marker_file())
    if not path.exists():
        return {}
    with open(path) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            content = f.read()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    if not content.strip():
        return {}
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def is_notified(project_file: str, changespec_name: str, entry_id: str) -> bool:
    """Return True if a mentors-complete notification has already been emitted."""
    return _key(project_file, changespec_name, entry_id) in _load()


def mark_notified(project_file: str, changespec_name: str, entry_id: str) -> None:
    """Record that a mentors-complete notification was emitted for this entry."""
    os.makedirs(_marker_dir(), exist_ok=True)
    key = _key(project_file, changespec_name, entry_id)
    timestamp = datetime.now(get_timezone()).isoformat()

    # Open with O_RDWR | O_CREAT so we can lock and rewrite atomically.
    fd = os.open(_marker_file(), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        with os.fdopen(fd, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                content = f.read()
                if content.strip():
                    try:
                        data = json.loads(content)
                        if not isinstance(data, dict):
                            data = {}
                    except json.JSONDecodeError:
                        data = {}
                else:
                    data = {}
                data[key] = timestamp
                f.seek(0)
                f.truncate()
                f.write(json.dumps(data))
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        # Re-raise after closing — but fdopen above already wrapped close.
        raise
