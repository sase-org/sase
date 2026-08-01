from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sase.agent_clis.runner import (
    _CommandExecutionError,
    _CommandNotFoundError,
    _CommandTimedOutError,
    run_command,
)
from sase.core.paths import get_sase_managed_tmpdir


def test_run_command_captures_nonzero_without_shell() -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 7, stdout="out", stderr="err")

    result = run_command(["tool", "update"], run_fn=fake_run, clock=lambda: 1.0)

    assert result.returncode == 7
    assert result.output == "err\nout"
    child_env = captured.pop("env")
    assert isinstance(child_env, dict)
    command_tmpdir = Path(child_env["TMPDIR"])
    assert command_tmpdir.parent == Path(get_sase_managed_tmpdir("agent-clis"))
    assert command_tmpdir.name.startswith("command-")
    assert not command_tmpdir.exists()
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


def test_run_command_routes_child_tempfiles_through_managed_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    watched_tmpdir = tmp_path / "watched"
    watched_tmpdir.mkdir()
    monkeypatch.setenv("TMPDIR", str(watched_tmpdir))

    result = run_command(
        [
            sys.executable,
            "-c",
            (
                "import tempfile; "
                "from pathlib import Path; "
                "root = Path(tempfile.gettempdir()); "
                "(root / 'opencode').mkdir(); "
                "print(root)"
            ),
        ]
    )

    assert result.returncode == 0
    command_tmpdir = Path(result.stdout.strip())
    assert command_tmpdir.parent == Path(get_sase_managed_tmpdir("agent-clis"))
    assert not command_tmpdir.exists()
    assert not (watched_tmpdir / "opencode").exists()
