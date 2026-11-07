"""Shared helpers for the artifact-link outbox drain.

Holds the lazily built agent catalog view the stale-terminal drop consults,
plus the cooperative deadline check the drain's per-row loops use, so the
drain module stays focused on partitioning and publication.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import time
from typing import Any

_TERMINAL_AGENT_STATES = frozenset({"completed", "failed", "stopped", "dismissed"})
_TERMINAL_AGENT_STATUSES = frozenset({"DONE", "FAILED", "STOPPED", "CANCELED"})
# Per-row loops consult the monotonic clock only this often.
_DEADLINE_CHECK_STRIDE = 256


class DrainDeadlineExceeded(Exception):
    """A drain's monotonic deadline passed before it started mutating state."""


def check_drain_deadline(deadline: float | None, index: int) -> None:
    """Raise :class:`DrainDeadlineExceeded` once *deadline* has passed.

    Only every ``_DEADLINE_CHECK_STRIDE``-th *index* (including ``0``) reads
    the clock, so per-row loops stay cheap while still noticing an expired
    budget long before the hard kill.
    """

    if deadline is None or index % _DEADLINE_CHECK_STRIDE:
        return
    if time.monotonic() >= deadline:
        raise DrainDeadlineExceeded


class AgentTerminalTimes:
    """Lazily built, reusable map of terminal agents to their finish times.

    The agent catalog snapshot is expensive (seconds to tens of seconds), so
    one provider is built at most once and can be shared by every drain in a
    run. A build failure is cached and yields no finish times: the stale
    drop then fails closed and drops nothing.
    """

    def __init__(
        self,
        *,
        snapshot_builder: Callable[[], Any] | None = None,
    ) -> None:
        self._snapshot_builder = snapshot_builder
        self._finished: Mapping[str, float] | None = None
        self.built = False
        self.ok = False
        self.build_seconds = 0.0

    def finished_times(self, names: Iterable[str]) -> dict[str, float]:
        """Return terminal ``finished_at`` epochs for the agents in *names*."""

        wanted = set(names)
        if not wanted:
            return {}
        finished = self._ensure_built()
        return {name: finished[name] for name in wanted if name in finished}

    def _ensure_built(self) -> Mapping[str, float]:
        if self._finished is not None:
            return self._finished
        started = time.monotonic()
        try:
            builder = self._snapshot_builder or _build_agent_catalog_snapshot
            finished = _terminal_finished_times(builder().rows)
            self.ok = True
        except Exception:  # noqa: BLE001 - failing closed preserves the queue.
            finished = {}
            self.ok = False
        self.built = True
        self.build_seconds = time.monotonic() - started
        self._finished = finished
        return finished


def _build_agent_catalog_snapshot() -> Any:
    from sase.agents.catalog import build_agent_catalog_snapshot

    return build_agent_catalog_snapshot()


def _terminal_finished_times(rows: Iterable[Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in rows:
        state = (row.state or "").casefold()
        status = (row.status or "").upper()
        if (
            state not in _TERMINAL_AGENT_STATES
            and status not in _TERMINAL_AGENT_STATUSES
        ):
            continue
        if row.finished_at is not None:
            result[row.name] = float(row.finished_at)
    return result


__all__ = [
    "AgentTerminalTimes",
    "DrainDeadlineExceeded",
    "check_drain_deadline",
]
