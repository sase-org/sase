"""Hijack lock order and optional assertion-style tracing.

Parent-approved order (outer to inner):

``adoption -> gate/monitor lane -> gate follow-up -> hijack ledger/target
index -> patch_lock``.

Hijack-package sub-order for the ledger itself is ``target_index`` then
``apply`` then ``record`` then ``patch_lock``. ``cas_advance_record`` may
acquire ``target_index`` while already holding ``record`` when it moves a
terminal record and releases the target slot; that inversion is the one
documented exception. ``patch_lock`` stays innermost and is never taken
twice in one process. The ledger/target lock is never acquired from
inside an already-held ``patch_lock``.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sase.notification_gates.durability import file_lock

HIJACK_LOCK_ORDER: tuple[str, ...] = (
    "adoption",
    "gate_lane",
    "monitor_lane",
    "gate_followup",
    "target_index",
    "apply",
    "record",
    "patch_lock",
)

#: ``(held, acquired)`` pairs allowed against :data:`HIJACK_LOCK_ORDER`.
#: Terminal cleanup releases the target slot while the record lock is held.
_ALLOWED_INVERSIONS: frozenset[tuple[str, str]] = frozenset(
    {("record", "target_index")}
)

_LOCK_RANK = {name: index for index, name in enumerate(HIJACK_LOCK_ORDER)}

_state = threading.local()


def _tracing_enabled() -> bool:
    return bool(getattr(_state, "tracing", False))


def _record(action: str, name: str) -> None:
    if not _tracing_enabled():
        return
    events = getattr(_state, "events", None)
    if events is None:
        _state.events = events = []
    events.append((action, name))


def _check_acquire(name: str) -> None:
    if not _tracing_enabled():
        return
    held = list(getattr(_state, "held", []))
    if name in held:
        raise AssertionError(f"recursive hijack lock {name!r} while holding {held}")
    acquired_rank = _LOCK_RANK.get(name)
    if acquired_rank is None:
        raise AssertionError(f"unknown hijack lock {name!r}")
    for current in held:
        if (current, name) in _ALLOWED_INVERSIONS:
            continue
        current_rank = _LOCK_RANK.get(current)
        if current_rank is None:
            continue
        if acquired_rank < current_rank:
            raise AssertionError(
                f"lock order violation: acquired {name!r} while holding {current!r} "
                f"(held={held})"
            )


@contextmanager
def record_lock_hold(name: str) -> Iterator[None]:
    """Record that *name* is held, without acquiring a file lock.

    Use this around helpers that take ``patch_lock`` themselves so spawn
    admission can prove ``target_index`` is already held first.
    """
    _check_acquire(name)
    held = getattr(_state, "held", None)
    if held is None:
        _state.held = held = []
    held.append(name)
    _record("acquire", name)
    try:
        yield
    finally:
        current = getattr(_state, "held", [])
        if current and current[-1] == name:
            current.pop()
        elif name in current:
            current.remove(name)
        _record("release", name)


@contextmanager
def acquire_hijack_lock(
    name: str,
    path: Path,
    *,
    timeout: float | None = 10.0,
) -> Iterator[None]:
    """Acquire *path* and record it as hijack lock *name*."""
    _check_acquire(name)
    held = getattr(_state, "held", None)
    if held is None:
        _state.held = held = []
    with file_lock(path, timeout=timeout):
        held.append(name)
        _record("acquire", name)
        try:
            yield
        finally:
            current = getattr(_state, "held", [])
            if current and current[-1] == name:
                current.pop()
            elif name in current:
                current.remove(name)
            _record("release", name)


__all__ = [
    "HIJACK_LOCK_ORDER",
    "acquire_hijack_lock",
    "record_lock_hold",
]
