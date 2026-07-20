from __future__ import annotations

import subprocess

import pytest

from sase.agent_clis.runner import (
    _CommandExecutionError,
    _CommandNotFoundError,
    _CommandTimedOutError,
    run_command,
)


def test_run_command_captures_nonzero_without_shell() -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 7, stdout="out", stderr="err")

    result = run_command(["tool", "update"], run_fn=fake_run, clock=lambda: 1.0)

    assert result.returncode == 7
    assert result.output == "err\nout"
    assert captured == {
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "timeout": 300.0,
        "check": False,
    }


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (FileNotFoundError(), _CommandNotFoundError),
        (subprocess.TimeoutExpired("tool", 1), _CommandTimedOutError),
        (PermissionError("denied"), _CommandExecutionError),
    ],
)
def test_run_command_maps_startup_errors(
    error: BaseException, expected: type[Exception]
) -> None:
    def fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise error

    with pytest.raises(expected):
        run_command(["tool"], run_fn=fail)
