"""Shared progress-event fakes for dev-update tests.

Provides a recording :class:`UpdateProgress` fake and a streaming-capable
command runner used by the planning and execution progress tests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from sase.dev_update.models import DevCommandResult, OutputSink
from sase.update_progress import StepSpec, StepStatus
from tests.dev_update._execute_helpers import FakeRunner


class RecordingProgress:
    """In-memory :class:`UpdateProgress` recording every event in order."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def declare(self, specs: Sequence[StepSpec]) -> None:
        self.events.append(
            ("declare", tuple((spec.id, spec.title, spec.parent_id) for spec in specs))
        )

    def start(
        self, id: str, *, title: str | None = None, detail: str | None = None
    ) -> None:
        self.events.append(("start", id, title, detail))

    def output(self, id: str, stream: str, line: str) -> None:
        self.events.append(("output", id, stream, line))

    def finish(self, id: str, status: StepStatus, *, detail: str | None = None) -> None:
        self.events.append(("finish", id, status, detail))

    def command(self, id: str, argv: Sequence[str], cwd: str | None = None) -> None:
        self.events.append(("command", id, tuple(argv), cwd))

    def finalize(
        self,
        status_for_pending: StepStatus = "skipped",
        *,
        status_for_running: StepStatus | None = None,
    ) -> None:
        self.events.append(("finalize", status_for_pending, status_for_running))

    def output_sink(self, id: str) -> OutputSink:
        def sink(stream: str, line: str) -> None:
            self.output(id, stream, line)

        return sink

    def finishes(self, id: str) -> list[tuple]:
        return [event for event in self.events if event[:2] == ("finish", id)]

    def outputs(self, id: str) -> list[tuple]:
        return [event for event in self.events if event[:2] == ("output", id)]


class StreamingRunner(FakeRunner):
    """Fake runner that accepts ``on_output`` and replays canned lines."""

    def __init__(
        self,
        responses: dict[tuple[str, ...], DevCommandResult] | None = None,
        *,
        emit: dict[tuple[str, ...], list[tuple[str, str]]] | None = None,
        sequences: dict[tuple[str, ...], list[DevCommandResult]] | None = None,
    ) -> None:
        super().__init__(responses)
        self.emit = emit or {}
        self.sequences = sequences or {}
        self.sink_calls: list[tuple[tuple[str, ...], bool]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        on_output: OutputSink | None = None,
    ) -> DevCommandResult:
        command = tuple(argv)
        self.calls.append((command, cwd))
        self.env_calls.append((command, cwd, dict(env) if env is not None else None))
        self.timeout_calls.append((command, timeout))
        self.sink_calls.append((command, on_output is not None))
        if on_output is not None:
            for stream, line in self.emit.get(command, []):
                on_output(stream, line)
        if command in self.sequences and self.sequences[command]:
            return self.sequences[command].pop(0)
        if command in self.responses:
            return self.responses[command]
        if command[:5] == ("git", "-C", "/repo", "status", "--porcelain"):
            return DevCommandResult(0, stdout="")
        if command[:6] == (
            "git",
            "-C",
            "/repo",
            "rev-list",
            "--left-right",
            "--count",
        ):
            return DevCommandResult(0, stdout="0 2")
        if command[:5] == ("git", "-C", "/repo", "rev-parse", "HEAD"):
            return DevCommandResult(0, stdout="abc123\n")
        return DevCommandResult(0)
