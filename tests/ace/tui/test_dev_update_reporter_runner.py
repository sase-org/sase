"""Tests for the ACE dev-update tracked-task runner adapter."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

import pytest

from sase.ace.tui.modals.plugins_browser_sase_update_tasks import (
    dev_update_reporter_runner,
)


class RaisingReporter:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.phases: list[str] = []
        self.calls: list[tuple[tuple[object, ...], Any, Any]] = []

    def phase(self, label: str) -> None:
        self.phases.append(label)

    def run(
        self,
        argv: Sequence[object],
        *,
        cwd: Any = None,
        env: Any = None,
    ) -> NoReturn:
        self.calls.append((tuple(argv), cwd, env))
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "expected_returncode", "expected_stderr"),
    [
        (
            FileNotFoundError(2, "No such file or directory", "just"),
            127,
            "just",
        ),
        (
            subprocess.TimeoutExpired(["just"], timeout=3.0),
            124,
            "command timed out",
        ),
        (OSError("permission denied"), 1, "permission denied"),
    ],
)
def test_dev_update_reporter_runner_maps_launch_failures(
    exc: BaseException,
    expected_returncode: int,
    expected_stderr: str,
) -> None:
    reporter = RaisingReporter(exc)
    runner = dev_update_reporter_runner(reporter)  # type: ignore[arg-type]
    argv = ("just", "rust-dev-install-uv-tool")
    cwd = Path("/repo")
    env = {"PATH": "/sentinel/bin"}

    result = runner(argv, cwd=cwd, env=env)

    assert result.returncode == expected_returncode
    assert expected_stderr in result.stderr
    assert reporter.phases == ["Running just rust-dev-install-uv-tool"]
    assert reporter.calls == [(argv, cwd, env)]
