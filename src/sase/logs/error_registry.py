"""Session-scoped pointer to the most recently registered ACE error.

Registration is in-memory only: a toast that names ``,L`` (or the configured
chord) is produced by the same helper that writes this pointer, so the chord
always has a real target. The durable log entry lives in
``launch_failures.log`` / ``.jsonl`` and carries the same ``error_id``.

``register_error`` is safe to call from the Textual event loop and from
``asyncio.to_thread`` workers; it does no disk I/O.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sase.core.time import get_timezone

_ERROR_ID_RANDOM_LEN = 6
_lock = threading.Lock()


@dataclass(frozen=True)
class RegisteredError:
    """One ACE-session error that ``,L`` can jump to."""

    error_id: str
    source_id: str
    anchor: str
    summary: str
    registered_at: str


_last: RegisteredError | None = None


def new_error_id() -> str:
    """Mint a sortable, greppable error id: ``err_<yymmdd_HHMMSS>_<6 hex>``."""
    stamp = datetime.now(get_timezone()).strftime("%y%m%d_%H%M%S")
    suffix = uuid4().hex[:_ERROR_ID_RANDOM_LEN]
    return f"err_{stamp}_{suffix}"


def error_anchor(error_id: str) -> str:
    """Return the exact substring stamped on a launch-failure header line."""
    return f"[{error_id}]"


def register_error(
    *,
    error_id: str,
    source_id: str,
    summary: str,
) -> RegisteredError:
    """Record *error_id* as this process's last registered error.

    Cheap enough for the event loop: in-memory, no disk I/O. Last write wins.
    """
    global _last
    record = RegisteredError(
        error_id=error_id,
        source_id=source_id,
        anchor=error_anchor(error_id),
        summary=summary,
        registered_at=datetime.now(get_timezone()).strftime("%Y-%m-%d %H:%M:%S"),
    )
    with _lock:
        _last = record
    return record


def last_registered_error() -> RegisteredError | None:
    """Return this process's last registered error, if any."""
    with _lock:
        return _last


def clear_registered_errors() -> None:
    """Drop the session pointer. Test seam."""
    global _last
    with _lock:
        _last = None


__all__ = [
    "RegisteredError",
    "clear_registered_errors",
    "error_anchor",
    "last_registered_error",
    "new_error_id",
    "register_error",
]
