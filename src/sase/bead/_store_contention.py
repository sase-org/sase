"""Bead-store lock contention handling for ``sase bead work`` launches.

The Rust core takes the bead mutation lock *before* it touches the store, so a
``lock_timeout`` failure means the requested mutation never ran. That makes it
the one launch failure that is safe to retry verbatim, and the one that should
be reported to the operator as a wait rather than a crash.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


BEAD_MUTATION_HOLDER_FILENAME = ".bead-mutation-lock.holder"
"""Sibling file sase-core writes while it holds the bead mutation lock."""

_LOCK_TIMEOUT_MARKER = "lock_timeout:"
_DEFAULT_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2.0
_UNKNOWN_HOLDER = "an unrecorded process"


class BeadStoreContentionError(RuntimeError):
    """A launch mutation that never ran because the bead store stayed locked."""


def is_bead_store_lock_timeout(exc: BaseException) -> bool:
    """Report whether *exc* is a core bead-store lock expiry."""
    return _LOCK_TIMEOUT_MARKER in str(exc).lower()


def _describe_bead_store_holder(beads_dir: Path | str) -> str:
    """Describe the recorded bead mutation lock holder for *beads_dir*.

    The holder file is best-effort on the writing side, so an unreadable,
    missing, or malformed record degrades to a generic description instead of
    failing the caller.
    """
    holder_path = Path(beads_dir) / BEAD_MUTATION_HOLDER_FILENAME
    try:
        record = json.loads(holder_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _UNKNOWN_HOLDER
    if not isinstance(record, dict):
        return _UNKNOWN_HOLDER
    return (
        f"pid={record.get('pid', '?')} "
        f"operation={record.get('operation', '?')} "
        f"since={record.get('acquired_at', '?')}"
    )


def retry_bead_store_mutation[T](
    mutation: Callable[[], T],
    *,
    beads_dir: Path | str,
    what: str,
    resume_command: str,
    attempts: int = _DEFAULT_ATTEMPTS,
) -> T:
    """Run *mutation*, retrying only while the bead store lock is contended.

    *what* names the mutation as a verb phrase (``"preclaim task sase-d8"``)
    and *resume_command* is the exact command that resumes the launch. Every
    failure other than a lock expiry propagates untouched, so a mutation that
    already reached the store is never repeated. An exhausted budget raises
    :class:`BeadStoreContentionError` naming the holder and the resume command.
    """
    budget = max(1, attempts)
    for attempt in range(1, budget + 1):
        try:
            return mutation()
        except Exception as exc:
            if not is_bead_store_lock_timeout(exc):
                raise
            holder = _describe_bead_store_holder(beads_dir)
            if attempt >= budget:
                raise BeadStoreContentionError(
                    f"gave up waiting for the bead store to {what} after "
                    f"{budget} attempts; the mutation lock is held by "
                    f"{holder}. Nothing was claimed — resume with "
                    f"`{resume_command}` once the holder releases it."
                ) from exc
            print(
                f"Waiting for the bead store to {what} "
                f"(attempt {attempt} of {budget}, held by {holder})..."
            )
            _sleep_before_retry(attempt)
    raise AssertionError("bead store retry budget ended without an outcome")


def _sleep_before_retry(attempt: int) -> None:
    delay = _RETRY_DELAY_SECONDS * attempt
    time.sleep(random.uniform(delay / 2, delay * 3 / 2))


__all__ = [
    "BEAD_MUTATION_HOLDER_FILENAME",
    "BeadStoreContentionError",
    "is_bead_store_lock_timeout",
    "retry_bead_store_mutation",
]
