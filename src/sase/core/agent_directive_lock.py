"""Lock helpers shared by agent directive writers.

Moved out of the TUI so the chop and the runner can serialize
``waiting.json`` writes without importing TUI actions. ``persist_agent_directive_update``
and ``_write_waiting_marker`` keep the same lock order through these functions:
``agent_directive_lock`` outside, ``runner_slot_marker_lock`` inside.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def agent_directive_lock(artifacts_path: Path) -> Iterator[None]:
    """Hold the exclusive directive lock for one artifacts directory."""
    import fcntl

    artifacts_path.mkdir(parents=True, exist_ok=True)
    lock_path = artifacts_path / ".agent_directive_persistence.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def runner_slot_marker_lock() -> Iterator[None]:
    """Hold the runner-slot marker lock (admission poller critical section)."""
    from sase.core.runner_slots import runner_slot_admission_lock

    with runner_slot_admission_lock():
        yield


__all__ = ["agent_directive_lock", "runner_slot_marker_lock"]
