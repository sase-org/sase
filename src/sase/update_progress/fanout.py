"""Fan-out sink that forwards every event while isolating failures."""

from __future__ import annotations

from collections.abc import Sequence

from .events import OutputSink, StepSpec, StepStatus, UpdateProgress


class FanOutProgress:
    """Forward every progress event to each child sink.

    One sink's exception never reaches the others or the caller, so progress
    stays purely observational no matter what a renderer does.
    """

    def __init__(self, *sinks: UpdateProgress) -> None:
        """Fan out to ``sinks`` in order."""
        self._sinks = list(sinks)

    @property
    def sinks(self) -> tuple[UpdateProgress, ...]:
        """Return the child sinks."""
        return tuple(self._sinks)

    def declare(self, specs: Sequence[StepSpec]) -> None:
        """Forward step declarations."""
        for sink in self._sinks:
            try:
                sink.declare(specs)
            except Exception:  # noqa: BLE001, S110 - progress must never fail a run
                pass

    def start(
        self, id: str, *, title: str | None = None, detail: str | None = None
    ) -> None:
        """Forward step starts."""
        for sink in self._sinks:
            try:
                sink.start(id, title=title, detail=detail)
            except Exception:  # noqa: BLE001, S110 - progress must never fail a run
                pass

    def output(self, id: str, stream: str, line: str) -> None:
        """Forward step output lines."""
        for sink in self._sinks:
            try:
                sink.output(id, stream, line)
            except Exception:  # noqa: BLE001, S110 - progress must never fail a run
                pass

    def finish(self, id: str, status: StepStatus, *, detail: str | None = None) -> None:
        """Forward step finishes."""
        for sink in self._sinks:
            try:
                sink.finish(id, status, detail=detail)
            except Exception:  # noqa: BLE001, S110 - progress must never fail a run
                pass

    def command(self, id: str, argv: Sequence[str], cwd: str | None = None) -> None:
        """Forward streamed command records."""
        for sink in self._sinks:
            try:
                sink.command(id, argv, cwd)
            except Exception:  # noqa: BLE001, S110 - progress must never fail a run
                pass

    def finalize(self, status_for_pending: StepStatus = "skipped") -> None:
        """Forward finalization."""
        for sink in self._sinks:
            try:
                sink.finalize(status_for_pending)
            except Exception:  # noqa: BLE001, S110 - progress must never fail a run
                pass

    def output_sink(self, id: str) -> OutputSink:
        """Return a sink that forwards ``(stream, line)`` to every child."""

        def sink(stream: str, line: str) -> None:
            self.output(id, stream, line)

        return sink
