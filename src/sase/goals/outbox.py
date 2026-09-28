"""Unpublished goals outbox (epic sase-1bu, phase publish-sync).

When a shared-mode publish fails or times out, the write is durable
locally and this outbox records the debt at
``~/.sase/projects/<key>/goals-outbox.json``::

    {"pending": true, "since": "<iso>", "attempts": 1,
     "last_error": "timeout", "last_attempt_at": "<iso>"}

It is cleared on the next successful publish. A missing or corrupt file
reads as not pending and never fails a command.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_goals_outbox(outbox_path: str | Path) -> dict[str, Any]:
    """Return the outbox record; missing/corrupt reads as not pending."""
    path = Path(outbox_path)
    empty: dict[str, Any] = {
        "pending": False,
        "since": None,
        "attempts": 0,
        "last_error": None,
        "last_attempt_at": None,
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(payload, dict):
        return empty
    pending = payload.get("pending") is True
    attempts = payload.get("attempts", 0)
    try:
        attempts = int(attempts)
    except (TypeError, ValueError):
        attempts = 0
    return {
        "pending": pending,
        "since": payload.get("since"),
        "attempts": max(0, attempts),
        "last_error": payload.get("last_error"),
        "last_attempt_at": payload.get("last_attempt_at"),
    }


def goals_outbox_pending(outbox_path: str | Path) -> bool:
    """Return True when *outbox_path* records an unpublished publish."""
    return bool(read_goals_outbox(outbox_path).get("pending"))


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record_goals_publish_failure(
    outbox_path: str | Path, error: str | None
) -> dict[str, Any]:
    """Record a failed/timed-out publish; return the new outbox record."""
    path = Path(outbox_path)
    previous = read_goals_outbox(path)
    now = _utc_now_iso()
    record: dict[str, Any] = {
        "pending": True,
        "since": previous.get("since") or now,
        "attempts": int(previous.get("attempts", 0) or 0) + 1,
        "last_error": error,
        "last_attempt_at": now,
    }
    try:
        _write_atomic(path, record)
    except Exception as exc:  # noqa: BLE001 - outbox write never fails a write.
        logger.warning("goals outbox write failed for %s: %s", path, exc)
    return record


def clear_goals_outbox(outbox_path: str | Path) -> dict[str, Any]:
    """Clear a pending publish; return the cleared (not-pending) record."""
    path = Path(outbox_path)
    record: dict[str, Any] = {
        "pending": False,
        "since": None,
        "attempts": 0,
        "last_error": None,
        "last_attempt_at": None,
    }
    try:
        if path.exists():
            path.unlink()
    except Exception as exc:  # noqa: BLE001 - outbox clear never fails a command.
        logger.warning("goals outbox clear failed for %s: %s", path, exc)
    return record
