"""Shared support for the contention soak contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests._contention import FAILURES_ENV, write_failures


class FakeSampler:
    """Stands in for ``tests._contention_sampler.start_sampler`` and its handle."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.starts: list[dict[str, Any]] = []
        self.stops = 0

    def start(self, out: Path, **kwargs: Any) -> FakeSampler | None:
        self.starts.append({"out": out, **kwargs})
        return self if self.available else None

    def stop(self) -> int:
        self.stops += 1
        return 0


class RecordedRepeat:
    """One intercepted repeat: the command, its environment, and its verdict."""

    def __init__(self, command: list[str], env: dict[str, str]) -> None:
        self.command = command
        self.env = env

    def complete(self, failures: tuple[str, ...] | None) -> None:
        if failures is not None:
            write_failures(Path(self.env[FAILURES_ENV]), failures)


def install_fake_repeats(
    runner: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    outcomes: list[tuple[int, tuple[str, ...] | None]],
    sampler: FakeSampler | None = None,
) -> list[RecordedRepeat]:
    """Stand in for the pytest subprocess each repeat launches.

    Each entry in ``outcomes`` is one repeat's ``(exit status, failing node
    IDs)``; a ``None`` node tuple is a repeat that wrote no record at all,
    which is what a hard crash leaves behind.
    """
    recorded: list[RecordedRepeat] = []
    artifacts = tmp_path / "contention-artifacts"
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(tmp_path / "scratch"))
    monkeypatch.setattr(runner, "CONTENTION_ARTIFACT_DIRECTORY", artifacts)

    class Result:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def fake_run(command: list[str], **kwargs: Any) -> Result:
        repeat = RecordedRepeat(list(command), dict(kwargs["env"]))
        returncode, failures = outcomes[len(recorded)]
        recorded.append(repeat)
        repeat.complete(failures)
        return Result(returncode)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    # Diagnostics have their own tests; these never start a real sampler.
    monkeypatch.setattr(runner, "start_sampler", (sampler or FakeSampler()).start)
    return recorded
