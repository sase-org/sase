"""Thread-safe timeline model implementing the progress event protocol."""

from __future__ import annotations

import threading
import time

from collections import deque
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field

from .events import TERMINAL_STATUSES, OutputSink, StepSpec, StepStatus

_TAIL_CAPACITY = 200
"""Lines of live output retained per step."""


@dataclass(frozen=True)
class StepSnapshot:
    """Immutable view of one step for renderers."""

    id: str
    title: str
    parent_id: str | None
    status: StepStatus
    detail: str | None
    started_at: float | None
    ended_at: float | None
    tail: tuple[str, ...] = ()
    children: tuple[StepSnapshot, ...] = ()


@dataclass
class _Step:
    id: str
    title: str
    parent_id: str | None = None
    status: StepStatus = "pending"
    detail: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    tail: deque[str] = field(default_factory=lambda: deque(maxlen=_TAIL_CAPACITY))
    children: list[_Step] = field(default_factory=list)


class TimelineModel:
    """Ordered, thread-safe store of timeline steps.

    Pure apart from the injected monotonic ``clock``: deterministic under a
    fake clock. Every method takes an internal lock, so streaming-runner pump
    threads may call :meth:`output` while the main thread finishes steps.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """Create an empty model reading time from ``clock``."""
        self._clock = clock
        self._lock = threading.Lock()
        self._steps: dict[str, _Step] = {}

    def declare(self, specs: Sequence[StepSpec]) -> None:
        """Register steps up front; re-declaring an id only refreshes its title."""
        with self._lock:
            for spec in specs:
                existing = self._steps.get(spec.id)
                if existing is not None:
                    existing.title = spec.title
                    continue
                parent_id = spec.parent_id
                if parent_id is not None and parent_id not in self._steps:
                    self._steps[parent_id] = _Step(id=parent_id, title=parent_id)
                self._steps[spec.id] = _Step(
                    id=spec.id, title=spec.title, parent_id=parent_id
                )
                if parent_id is not None:
                    self._steps[parent_id].children.append(self._steps[spec.id])

    def start(
        self, id: str, *, title: str | None = None, detail: str | None = None
    ) -> None:
        """Mark a step running, auto-appending undeclared ids as top-level rows."""
        with self._lock:
            step = self._steps.get(id)
            if step is None:
                step = _Step(id=id, title=title or id)
                self._steps[id] = step
            if title is not None:
                step.title = title
            if detail is not None:
                step.detail = detail
            if step.status != "running":
                step.status = "running"
                step.started_at = self._clock()
                step.ended_at = None

    def output(self, id: str, stream: str, line: str) -> None:
        """Append one output line to a step's bounded tail."""
        del stream
        with self._lock:
            step = self._steps.get(id)
            if step is None:
                step = _Step(id=id, title=id)
                self._steps[id] = step
            step.tail.append(line)

    def finish(self, id: str, status: StepStatus, *, detail: str | None = None) -> None:
        """Finish a step; finishing a parent skips its still-running children.

        First write wins: finishing an already-finished step is a no-op, so a
        ``step()`` context manager never clobbers a detail set explicitly.
        """
        with self._lock:
            step = self._steps.get(id)
            if step is None:
                step = _Step(id=id, title=id)
                self._steps[id] = step
            if step.status in TERMINAL_STATUSES:
                return
            now = self._clock()
            step.status = status
            if detail is not None:
                step.detail = detail
            step.ended_at = now
            for child in step.children:
                self._finish_child_locked(child, now)

    def _finish_child_locked(self, step: _Step, now: float) -> None:
        if step.status == "running":
            step.status = "skipped"
            step.ended_at = now
            for child in step.children:
                self._finish_child_locked(child, now)

    def command(self, id: str, argv: Sequence[str], cwd: str | None = None) -> None:
        """Ignore streamed command records; they exist for the log sink."""
        del id, argv, cwd

    def finalize(self, status_for_pending: StepStatus = "skipped") -> None:
        """Mark every still-pending or still-running step with the given status."""
        with self._lock:
            now = self._clock()
            for step in self._steps.values():
                if step.status not in TERMINAL_STATUSES:
                    step.status = status_for_pending
                    if step.ended_at is None:
                        step.ended_at = now

    def output_sink(self, id: str) -> OutputSink:
        """Return an :data:`OutputSink` bound to a step."""

        def sink(stream: str, line: str) -> None:
            self.output(id, stream, line)

        return sink

    def snapshot(self) -> tuple[StepSnapshot, ...]:
        """Return immutable top-level rows with nested children, in order."""
        with self._lock:
            return tuple(
                self._freeze(step)
                for step in self._steps.values()
                if step.parent_id is None
            )

    def _freeze(self, step: _Step) -> StepSnapshot:
        return StepSnapshot(
            id=step.id,
            title=step.title,
            parent_id=step.parent_id,
            status=step.status,
            detail=step.detail,
            started_at=step.started_at,
            ended_at=step.ended_at,
            tail=tuple(step.tail),
            children=tuple(self._freeze(child) for child in step.children),
        )


def walk(snapshot: Sequence[StepSnapshot]) -> Iterator[tuple[int, StepSnapshot]]:
    """Yield ``(depth, row)`` pairs in display order, children after parents."""
    for row in snapshot:
        yield 0, row
        for child in row.children:
            yield from _walk_child(child, 1)


def _walk_child(row: StepSnapshot, depth: int) -> Iterator[tuple[int, StepSnapshot]]:
    yield depth, row
    for child in row.children:
        yield from _walk_child(child, depth + 1)


def elapsed(row: StepSnapshot, now: float) -> float:
    """Return seconds since a step started (0 for never-started steps)."""
    if row.started_at is None:
        return 0.0
    end = row.ended_at if row.ended_at is not None else now
    return max(0.0, end - row.started_at)
