"""Process-local view of code swaps: did one happen under this process?

A code swap (``sase dev update``, ``just install``, ``just install-dev``)
replaces SASE's Python sources, console scripts, and the ``sase_core_rs``
extension under processes that are already running. A process that booted
before the swap keeps the modules it already imported but resolves every
*later* import against the new tree. It can then mix versions (``cannot
import name 'BeforeSpawnCallback'``) or find the binding missing mid-copy.

This module answers that question cheaply and never raises:

* :func:`code_swap_writer_live` reports whether a swap is in progress now.
* :func:`code_swap_since_boot` reports whether a swap completed after this
  process recorded its boot generation with
  :func:`snapshot_boot_swap_generation`.
* :func:`code_swap_in_play` describes either of those, or a swap that
  completed within the post-swap grace window.
* :func:`long_lived_swap_guard` builds the predicate a long-lived process
  checks before it starts in-process work that imports lazily.
* :func:`wait_for_code_swap_writer` polls until no writer holds the lock.

It reads the writer holder payload in the code-swap lock file and the
last-swap stamp directly. At module load it imports only the standard library
and :mod:`sase.core.paths`, because ``sase.dev_update``'s package
``__init__`` costs hundreds of milliseconds, and a process torn by a swap must
still be able to call these. The filenames and the grace window mirror
:mod:`sase.dev_update.code_swap_lock` and :mod:`sase.dev_update.code_swap_stamp`;
a parity test pins them together.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sase.core.paths import sase_subdir

#: Mirrors ``code_swap_lock.CODE_SWAP_LOCK_FILENAME``.
_LOCK_FILENAME = "code-swap-v2.lock"
#: Mirrors ``code_swap_stamp.CODE_SWAP_LAST_SWAP_FILENAME``.
_STAMP_FILENAME = "code-swap-last.json"
#: Mirrors ``code_swap_stamp.CODE_SWAP_GRACE_SECONDS``.
_GRACE_SECONDS = 120.0
#: Mirrors ``code_swap_lock.ENV_DISABLE_CODE_SWAP_LOCK``.
_ENV_DISABLE = "SASE_DISABLE_CODE_SWAP_LOCK"


@dataclass(frozen=True)
class _SwapEpoch:
    """The last-swap generation one process observed in one lock directory."""

    locks_dir: Path
    generation: int


_boot_epoch: _SwapEpoch | None = None


def snapshot_boot_swap_generation() -> None:
    """Record the code-swap generation this process booted against, once.

    Call it from a process entry point before the process imports anything
    swap-sensitive. Repeat calls keep the first snapshot, so a later swap can
    never overwrite the boot value.
    """
    global _boot_epoch  # noqa: PLW0603 - one snapshot per process by design
    if _boot_epoch is None:
        _boot_epoch = _current_epoch()


def code_swap_since_boot() -> bool:
    """Whether a swap completed after :func:`snapshot_boot_swap_generation`.

    ``False`` when no boot snapshot was taken, or when the state root moved
    since (a different stamp file is not comparable).
    """
    return _advanced_since(_boot_epoch)


def code_swap_writer_live() -> bool:
    """Whether a live code-swap writer holds the lock right now.

    Reads the writer's holder payload without taking any ``flock``, like
    ``code_swap_lock.code_swap_writer_holder``. A payload left by a dead
    writer reads as no swap.
    """
    try:
        if _disabled():
            return False
        raw = (_locks_dir() / _LOCK_FILENAME).read_text(encoding="utf-8").strip()
        if not raw:
            return False
        holder = json.loads(raw)
        if not isinstance(holder, dict):
            return False
        pid = int(holder.get("pid", ""))
        return pid > 0 and _pid_alive(pid)
    except Exception:  # noqa: BLE001 - a probe must never break its caller
        return False


def code_swap_in_play(*, now: datetime | None = None) -> str | None:
    """Describe why swap fallout is plausible right now, or ``None``.

    True when a writer is live, a swap completed since this process booted, or
    the last swap completed within the post-swap grace window. Callers combine
    this with a skew-looking failure before they defer or retry: the failure
    text alone is not enough.
    """
    if code_swap_writer_live():
        return "a code swap is in progress"
    if code_swap_since_boot():
        return "a code swap completed after this process started"
    age = _seconds_since_last_swap(now)
    if age is not None and abs(age) <= _GRACE_SECONDS:
        return (
            f"a code swap completed {max(0, int(age))}s ago, inside the "
            f"{int(_GRACE_SECONDS)}s post-swap grace"
        )
    return None


def long_lived_swap_guard() -> Callable[[], bool]:
    """Return a predicate that turns true once this process outlived a swap.

    The generation is captured when this factory runs, so call it at process
    start. The predicate is true while a writer is live or once a later swap
    completed. A long-lived process must then stop starting in-process work
    that imports lazily, and restart cleanly once no writer is live.
    """
    epoch = _current_epoch()

    def swapped() -> bool:
        return code_swap_writer_live() or _advanced_since(epoch)

    return swapped


def wait_for_code_swap_writer(
    *,
    timeout_seconds: float,
    poll_seconds: float = 1.0,
    on_wait: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Poll until no writer is live; return whether it cleared in time.

    *on_wait* runs once, before the first sleep, so a caller can say it is
    waiting. Holds nothing while it waits.
    """
    deadline = clock() + timeout_seconds
    notified = False
    while code_swap_writer_live():
        if clock() >= deadline:
            return False
        if not notified and on_wait is not None:
            notified = True
            on_wait()
        sleep(poll_seconds)
    return True


def _advanced_since(epoch: _SwapEpoch | None) -> bool:
    current = _current_epoch()
    if epoch is None or current is None:
        return False
    return current.locks_dir == epoch.locks_dir and (
        current.generation > epoch.generation
    )


def _current_epoch() -> _SwapEpoch | None:
    """Return the last-swap generation now (0 with no stamp), never raising."""
    try:
        locks_dir = _locks_dir()
        stamp = _read_stamp(locks_dir)
        generation = stamp.get("generation") if stamp is not None else None
        if isinstance(generation, bool) or not isinstance(generation, int):
            generation = 0
        return _SwapEpoch(locks_dir=locks_dir, generation=max(0, generation))
    except Exception:  # noqa: BLE001 - a probe must never break its caller
        return None


def _seconds_since_last_swap(now: datetime | None) -> float | None:
    try:
        stamp = _read_stamp(_locks_dir())
        raw = stamp.get("completed_at") if stamp is not None else None
        if not isinstance(raw, str) or not raw:
            return None
        completed_at = datetime.fromisoformat(raw)
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=UTC)
        current = now if now is not None else datetime.now(UTC)
        return (current - completed_at).total_seconds()
    except Exception:  # noqa: BLE001 - a bad stamp reads as no swap
        return None


def _read_stamp(locks_dir: Path) -> dict[str, object] | None:
    if _disabled():
        return None
    try:
        raw = json.loads((locks_dir / _STAMP_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return raw if isinstance(raw, dict) else None


def _locks_dir() -> Path:
    return sase_subdir("locks")


def _disabled() -> bool:
    return os.environ.get(_ENV_DISABLE) == "1"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as status:
            for line in status:
                if line.startswith("State:"):
                    return "Z" not in line
    except OSError:
        pass
    return True


__all__ = [
    "code_swap_in_play",
    "code_swap_since_boot",
    "code_swap_writer_live",
    "long_lived_swap_guard",
    "snapshot_boot_swap_generation",
    "wait_for_code_swap_writer",
]
