"""Progress event protocol for live `sase update` timelines.

Backends (dev-update, uv, mode-switch) only know this protocol. The default
sink is a no-op, so progress is purely observational: no rendering failure
can fail an update.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, Protocol
from collections.abc import Iterator

StepStatus = Literal[
    "pending", "running", "done", "warned", "failed", "skipped", "interrupted"
]
"""Lifecycle states for one timeline step."""

TERMINAL_STATUSES: tuple[StepStatus, ...] = (
    "done",
    "warned",
    "failed",
    "skipped",
    "interrupted",
)
"""Statuses after which a step is considered finished."""

OutputSink = Callable[[str, str], None]
"""Subprocess output callback: ``(stream, line)``.

``stream`` is ``"stdout"`` or ``"stderr"``. This is the same shape as the
``OutputSink`` alias owned by ``sase.dev_update.models`` (defined there for
the streaming runner); the two aliases are structurally identical so a sink
built here plugs into either side.
"""


@dataclass(frozen=True)
class StepSpec:
    """Declaration of one timeline step."""

    id: str
    title: str
    parent_id: str | None = None


class UpdateProgress(Protocol):
    """Event sink protocol that backends emit progress into."""

    def declare(self, specs: Sequence[StepSpec]) -> None:
        """Register steps up front so renderers show pending rows."""
        ...

    def start(
        self, id: str, *, title: str | None = None, detail: str | None = None
    ) -> None:
        """Mark a step running. Auto-appends undeclared ids."""
        ...

    def output(self, id: str, stream: str, line: str) -> None:
        """Record one sanitized subprocess output line for a step."""
        ...

    def finish(self, id: str, status: StepStatus, *, detail: str | None = None) -> None:
        """Finish a step. First write wins; later finishes are ignored."""
        ...

    def command(self, id: str, argv: Sequence[str], cwd: str | None = None) -> None:
        """Record a streamed command line for the log. No-op by default."""
        ...

    def finalize(self, status_for_pending: StepStatus = "skipped") -> None:
        """Mark every still-pending or still-running step with the given status."""
        ...

    def output_sink(self, id: str) -> OutputSink:
        """Return an :data:`OutputSink` bound to a step."""
        ...


class NullProgress:
    """No-op :class:`UpdateProgress` used when no session is active."""

    def declare(self, specs: Sequence[StepSpec]) -> None:
        """Discard step declarations."""

    def start(
        self, id: str, *, title: str | None = None, detail: str | None = None
    ) -> None:
        """Discard step starts."""

    def output(self, id: str, stream: str, line: str) -> None:
        """Discard step output."""

    def finish(self, id: str, status: StepStatus, *, detail: str | None = None) -> None:
        """Discard step finishes."""

    def command(self, id: str, argv: Sequence[str], cwd: str | None = None) -> None:
        """Discard streamed command records."""

    def finalize(self, status_for_pending: StepStatus = "skipped") -> None:
        """Discard finalization."""

    def output_sink(self, id: str) -> OutputSink:
        """Return a sink that discards ``(stream, line)`` pairs."""
        return _discard_output


def _discard_output(stream: str, line: str) -> None:
    """Shared no-op output sink."""


NULL_PROGRESS = NullProgress()
"""Shared no-op sink. Backends default their ``progress`` keyword to this."""


@contextmanager
def step(
    progress: UpdateProgress,
    id: str,
    title: str | None = None,
    *,
    detail: str | None = None,
) -> Iterator[str]:
    """Run a block as a timeline step.

    Marks the step ``failed`` on exception (``interrupted`` on
    ``KeyboardInterrupt``) and re-raises. On clean exit the step is marked
    ``done`` only if the block did not finish it explicitly, so backends can
    set a result detail with :meth:`UpdateProgress.finish` and still use this
    helper for failure mapping.
    """
    if title is None:
        progress.start(id, detail=detail)
    else:
        progress.start(id, title=title, detail=detail)
    try:
        yield id
    except KeyboardInterrupt:
        progress.finish(id, "interrupted")
        raise
    except BaseException:
        progress.finish(id, "failed")
        raise
    else:
        progress.finish(id, "done")
