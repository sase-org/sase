"""Durable update-attempt journal for the updates gear.

Every call in this module blocks on a file lock and on atomic file writes, so
every call belongs off the UI thread; run them only in worker threads and
deliver their views to the UI through ``call_from_thread`` or worker results.
Failures are best-effort and never raise: on I/O trouble the caller gets the
view of the in-memory reduced record so its own outcome is still reflected.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from sase.ace._update_attempts_model import (
    UpdateAttempt,
    UpdateAttemptOwner,
    UpdateAttemptsRecord,
    UpdateAttemptsView,
    attempts_record_from_json,
    attempts_record_to_json,
    attempts_view,
    empty_attempts_record,
    is_foreign_attempts_schema,
    new_update_attempt,
    reduce_dismiss,
    reduce_reconcile,
    reduce_settle,
    reduce_start,
)
from sase.core.paths import sase_home
from sase.core.process_identity import (
    process_identity_matches,
    process_identity_token,
)
from sase.memory.locks import LockTimeoutError, locked_file

log = logging.getLogger(__name__)

_UPDATE_ATTEMPTS_FILE: Path | None = None

_LOCK_TIMEOUT_SECONDS = 2.0

CURRENT_INSTANCE_ID = uuid4().hex


def _current_owner() -> UpdateAttemptOwner:
    """Return the owner marker for this ACE process."""
    pid = os.getpid()
    return UpdateAttemptOwner(
        pid=pid,
        identity=process_identity_token(pid),
        instance_id=CURRENT_INSTANCE_ID,
    )


def _owner_is_alive(owner: UpdateAttemptOwner) -> bool:
    """Return whether the owner of an in-flight marker is still running.

    The instance id distinguishes the current incarnation from a previous one
    after an ``execv`` restart, which keeps the pid.
    """
    if owner.instance_id == CURRENT_INSTANCE_ID:
        return True
    if owner.pid == os.getpid() or owner.pid < 1:
        return False
    try:
        os.kill(owner.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return process_identity_matches(owner.pid, owner.identity)


def begin_update_attempt(attempt: UpdateAttempt) -> UpdateAttemptsView:
    """Persist the in-flight marker for *attempt* and return the view."""
    owner = _current_owner()
    now = time.time()
    return _apply_atomically(
        lambda record: reduce_start(record, attempt, owner, now=now)
    )


def settle_update_attempt(
    attempt: UpdateAttempt,
    *,
    success: bool,
    error: str | None,
    output: str | None,
) -> UpdateAttemptsView:
    """Remove the marker, fold the outcome in, and return the view."""
    now = time.time()
    return _apply_atomically(
        lambda record: reduce_settle(
            record, attempt, success=success, error=error, output=output, now=now
        )
    )


def dismiss_update_failure(attempt_id: str) -> UpdateAttemptsView:
    """Clear the recorded failure when its attempt id matches."""
    now = time.time()
    return _apply_atomically(lambda record: reduce_dismiss(record, attempt_id, now=now))


def load_update_attempts() -> UpdateAttemptsView:
    """Reconcile dead markers under the lock, writing only on change."""
    now = time.time()
    return _apply_atomically(
        lambda record: reduce_reconcile(record, _owner_is_alive, now=now)
    )


def _apply_atomically(
    reducer: Callable[[UpdateAttemptsRecord], tuple[UpdateAttemptsRecord, bool]],
) -> UpdateAttemptsView:
    path = _update_attempts_file()
    lock_path = path.with_name(path.name + ".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(lock_path, fcntl.LOCK_EX, timeout=_LOCK_TIMEOUT_SECONDS):
            record, foreign = _load_locked(path)
            if foreign:
                return UpdateAttemptsView(revision=0, failure=None)
            updated, changed = reducer(record)
            if changed:
                try:
                    _write_record(path, updated)
                except OSError:
                    log.debug(
                        "Failed to persist update attempts journal", exc_info=True
                    )
            return attempts_view(updated)
    except (OSError, LockTimeoutError):
        log.debug(
            "Update attempts journal unavailable; using in-memory view",
            exc_info=True,
        )
        updated, _ = reducer(empty_attempts_record())
        return attempts_view(updated)


def _load_locked(path: Path) -> tuple[UpdateAttemptsRecord, bool]:
    """Read the stored record; the second item flags a foreign schema."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_attempts_record(), False
    try:
        payload = json.loads(raw)
    except ValueError:
        log.debug("Ignoring malformed update attempts journal", exc_info=True)
        return empty_attempts_record(), False
    if is_foreign_attempts_schema(payload):
        return empty_attempts_record(), True
    record = attempts_record_from_json(payload)
    if record is None:
        log.debug("Ignoring malformed update attempts journal", exc_info=True)
        return empty_attempts_record(), False
    return record, False


def _write_record(path: Path, record: UpdateAttemptsRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=f".{os.getpid()}.tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            json.dump(attempts_record_to_json(record), tmp, sort_keys=True)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
    except OSError:
        if tmp_path is not None:
            _safe_unlink(tmp_path)
        raise


def _update_attempts_file() -> Path:
    return _UPDATE_ATTEMPTS_FILE or sase_home() / "update_attempts.json"


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        log.debug("Failed to remove update attempts temp file", exc_info=True)


__all__ = [
    "CURRENT_INSTANCE_ID",
    "UpdateAttempt",
    "UpdateAttemptOwner",
    "UpdateAttemptsRecord",
    "UpdateAttemptsView",
    "begin_update_attempt",
    "_current_owner",
    "dismiss_update_failure",
    "load_update_attempts",
    "new_update_attempt",
    "_owner_is_alive",
    "settle_update_attempt",
]
