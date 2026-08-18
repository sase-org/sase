"""Guard and write helpers for pending agent-handoff markers.

Kept out of :mod:`sase.agent.pending_handoff` so the runner's SIGTERM path
can keep its cheap read-only import.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.pending_handoff import PENDING_HANDOFF_MARKERS


class PendingHandoffError(RuntimeError):
    """Raised when a pending runner handoff cannot be started."""


def handoff_guard() -> str:
    """Return the caller's artifacts dir, or raise if a handoff cannot start."""
    if not os.environ.get("SASE_AGENT"):
        raise PendingHandoffError("SASE_AGENT is unset")
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        raise PendingHandoffError("SASE_ARTIFACTS_DIR is unset")
    existing = _existing_pending_markers(artifacts_dir)
    if existing:
        raise PendingHandoffError(_already_exists_message(existing))
    return artifacts_dir


def write_pending_handoff_marker(
    marker: str,
    payload: Mapping[str, Any],
    *,
    artifacts_dir: str | None = None,
) -> Path:
    """Stamp ``timestamp``, write ``marker`` atomically, and fsync it.

    ``timestamp`` is left alone when the payload already carries one so a
    caller can pin the value the runner later compares against the kill.
    """
    resolved = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not resolved:
        raise PendingHandoffError("SASE_ARTIFACTS_DIR is unset")
    if marker not in PENDING_HANDOFF_MARKERS:
        raise PendingHandoffError(f"unknown pending handoff marker: {marker}")
    existing = _existing_pending_markers(resolved)
    if existing:
        raise PendingHandoffError(_already_exists_message(existing))

    data = dict(payload)
    data.setdefault("timestamp", time.time())
    path = Path(resolved) / marker
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, data)
    return path


def _existing_pending_markers(artifacts_dir: str) -> tuple[str, ...]:
    root = Path(artifacts_dir)
    found: list[str] = []
    for name in PENDING_HANDOFF_MARKERS:
        try:
            if (root / name).exists():
                found.append(name)
        except OSError:
            continue
    return tuple(found)


def _already_exists_message(existing: tuple[str, ...]) -> str:
    return f"pending handoff already exists: {', '.join(existing)}"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    fd, temp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
