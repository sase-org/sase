"""Durable last-swap stamp recorded next to the code-swap writer lock.

Every code-swap writer records one small JSON document when it releases the
lock, while it still holds the exclusive ``flock``:

.. code-block:: json

    {"completed_at": "...", "generation": 7, "op": "dev.update",
     "pid": 1234, "started_at": "..."}

``started_at`` is when the writer took the lock and ``completed_at`` is when it
let go. ``generation`` grows by one per recorded swap, so a long-lived process
can tell that a swap happened since it last looked. The writers are
:func:`sase.dev_update.code_swap_lock.code_swap_writer_lock` (``sase dev
update``) and the stdlib-only installer's ``acquire_swap_lock`` in
``tools/_sase_install_run.py`` (``just install`` / ``just install-dev``), which
mirrors this shape; a parity test pins the two together.

Readers tolerate a missing or corrupt stamp as "no recent swap". This module
imports nothing from the rest of ``sase.dev_update`` so the lock module can
import it without a cycle.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir

_logger = logging.getLogger(__name__)

#: Filename of the last-swap stamp, a sibling of ``code-swap-v2.lock``.
CODE_SWAP_LAST_SWAP_FILENAME = "code-swap-last.json"

#: How long after a swap completes a vanished job script or binding still
#: counts as swap fallout (a deferral) rather than a broken install.
CODE_SWAP_GRACE_SECONDS = 120.0

# Mirrors ``code_swap_lock.ENV_DISABLE_CODE_SWAP_LOCK``; that module imports
# this one, so importing it back would be a cycle.
_ENV_DISABLE_CODE_SWAP_LOCK = "SASE_DISABLE_CODE_SWAP_LOCK"

_OP_DISPLAY_NAMES = {
    "bead.work": "sase bead work",
    "dev.update": "sase dev update",
    "agent.runner": "agent runner",
    "install.dev": "just install-dev",
    "install.pypi": "just install",
}


@dataclass(frozen=True)
class _LastCodeSwap:
    """The most recent completed code swap recorded by any writer."""

    op: str
    started_at: datetime
    completed_at: datetime
    generation: int

    def describe(self) -> str:
        """Return a short human description, e.g. for a deferral reason."""
        return (
            f"{display_code_swap_op(self.op)} swap #{self.generation}, "
            f"started {self.started_at.isoformat()}, "
            f"completed {self.completed_at.isoformat()}"
        )

    def overlaps(self, started_at: datetime, finished_at: datetime) -> bool:
        """Whether a run spanning *started_at*..*finished_at* overlapped it."""
        return started_at < self.completed_at and finished_at >= self.started_at

    def seconds_since_completed(self, now: datetime | None = None) -> float:
        current = now if now is not None else datetime.now(UTC)
        return (current - self.completed_at).total_seconds()


def display_code_swap_op(op: str) -> str:
    """Return the user-facing name for a code-swap lock holder ``op``."""
    return _OP_DISPLAY_NAMES.get(op, op)


def _last_code_swap_path() -> Path:
    return sase_subdir("locks") / CODE_SWAP_LAST_SWAP_FILENAME


def read_last_code_swap() -> _LastCodeSwap | None:
    """Return the recorded last swap, or ``None`` when there is none to trust.

    Never raises: a missing, unreadable, or malformed stamp reads as no swap.
    """
    try:
        if os.environ.get(_ENV_DISABLE_CODE_SWAP_LOCK) == "1":
            return None
        raw = json.loads(_last_code_swap_path().read_text(encoding="utf-8"))
        return _parse_stamp(raw)
    except Exception:  # noqa: BLE001 - a bad stamp must never break a reader
        return None


def recent_code_swap(
    *,
    now: datetime | None = None,
    grace_seconds: float = CODE_SWAP_GRACE_SECONDS,
) -> _LastCodeSwap | None:
    """Return the last swap when it completed within *grace_seconds* of *now*.

    The window is symmetric so a stamp from a skewed or rewound clock cannot
    inhibit work forever.
    """
    swap = read_last_code_swap()
    if swap is None:
        return None
    if abs(swap.seconds_since_completed(now)) > grace_seconds:
        return None
    return swap


def record_last_code_swap(*, op: str, started_at: str) -> _LastCodeSwap | None:
    """Record a completed swap; call while still holding the writer lock.

    Best-effort: a failed write is logged and returns ``None`` so releasing the
    lock is never blocked by the stamp. The write is atomic (temp file plus
    rename), and the generation increments the previous stamp's, starting at 1.
    """
    try:
        previous = read_last_code_swap()
        payload: dict[str, Any] = {
            "op": op,
            "pid": os.getpid(),
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "generation": (previous.generation if previous is not None else 0) + 1,
        }
        swap = _parse_stamp(payload)
        if swap is None:
            return None
        _write_atomic(_last_code_swap_path(), payload)
        return swap
    except Exception:  # noqa: BLE001 - never block the writer's release
        _logger.debug("Failed to record the last code swap", exc_info=True)
        return None


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True))
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _parse_stamp(raw: object) -> _LastCodeSwap | None:
    if not isinstance(raw, dict):
        return None
    op = raw.get("op")
    generation = raw.get("generation")
    if not isinstance(op, str) or not op:
        return None
    if isinstance(generation, bool) or not isinstance(generation, int):
        return None
    if generation < 1:
        return None
    started_at = _parse_time(raw.get("started_at"))
    completed_at = _parse_time(raw.get("completed_at"))
    if started_at is None or completed_at is None:
        return None
    return _LastCodeSwap(
        op=op,
        started_at=started_at,
        completed_at=completed_at,
        generation=generation,
    )


def _parse_time(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


__all__ = [
    "CODE_SWAP_GRACE_SECONDS",
    "CODE_SWAP_LAST_SWAP_FILENAME",
    "display_code_swap_op",
    "read_last_code_swap",
    "recent_code_swap",
    "record_last_code_swap",
]
