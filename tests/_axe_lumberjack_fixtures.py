"""Shared helpers for sase.axe.lumberjack tests."""

import subprocess
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.chop_script_runner import _StreamedScriptResult
from sase.axe.state import read_chop_run_index


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Redirect axe and lumberjack state to a temporary directory."""
    state_dir = tmp_path / ".sase" / "axe"
    lumberjack_dir = state_dir / "lumberjacks"
    with (
        patch("sase.axe.state.axe_state_dir", return_value=state_dir),
        patch("sase.axe.state.jack_state_dir", return_value=lumberjack_dir),
    ):
        yield state_dir


@pytest.fixture
def lumberjack_config() -> LumberjackConfig:
    return LumberjackConfig(
        name="test_lumberjack",
        description="Run lumberjack fixture chops",
        interval=10,
        chops=[ChopConfig(name="hook_checks", description="")],
    )


@pytest.fixture
def axe_config() -> AxeConfig:
    return AxeConfig(
        max_hook_runners=3, max_agent_runners=3, zombie_timeout_seconds=3600, query=""
    )


def ok_result() -> subprocess.CompletedProcess[str]:
    """Return a successful CompletedProcess for mocking ``run_chop_script``."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def fail_result(
    code: int = 1, stderr: str = "error"
) -> subprocess.CompletedProcess[str]:
    """Return a failed CompletedProcess for mocking ``run_chop_script``."""
    return subprocess.CompletedProcess(
        args=[], returncode=code, stdout="", stderr=stderr
    )


def streamed_ok(output: str = "", pid: int = 1234) -> "_StreamedSideEffect":
    """Side-effect callable simulating a successful streaming run.

    Writes ``output`` to ``log_path`` (the kwarg ``stream_chop_script``
    receives), invokes ``on_pid`` if provided, and returns a ``returncode=0``
    :class:`_StreamedScriptResult`.
    """
    return _StreamedSideEffect(returncode=0, output=output, pid=pid)


def streamed_fail(
    code: int = 1, output: str = "boom", pid: int = 1234
) -> "_StreamedSideEffect":
    """Side-effect callable simulating a non-zero exit with captured output."""
    return _StreamedSideEffect(returncode=code, output=output, pid=pid)


def streamed_timeout(output: str = "", pid: int = 1234) -> "_StreamedSideEffect":
    """Side-effect callable simulating a timeout (kill before reporting exit)."""
    return _StreamedSideEffect(returncode=None, output=output, pid=pid, timed_out=True)


class _StreamedSideEffect:
    """Callable side_effect for patching ``stream_chop_script``.

    Mimics the real streaming runner: writes ``output`` bytes into the
    ``log_path`` Path argument (so collector/log-tail readers see them),
    invokes ``on_pid`` with ``pid`` to exercise PID-recording paths, and
    returns a :class:`_StreamedScriptResult` describing the outcome.
    """

    def __init__(
        self,
        *,
        returncode: int | None,
        output: str = "",
        pid: int = 1234,
        timed_out: bool = False,
    ) -> None:
        self.returncode = returncode
        self.output = output
        self.pid = pid
        self.timed_out = timed_out

    def __call__(self, *args: object, **kwargs: object) -> _StreamedScriptResult:
        log_path = kwargs.get("log_path")
        bytes_written = 0
        if isinstance(log_path, Path) and self.output:
            data = self.output.encode("utf-8")
            with open(log_path, "ab") as f:
                f.write(data)
            bytes_written = len(data)
        on_pid = kwargs.get("on_pid")
        if callable(on_pid):
            on_pid(self.pid)
        return _StreamedScriptResult(
            returncode=self.returncode,
            pid=self.pid,
            output_bytes=bytes_written,
            timed_out=self.timed_out,
        )


def streamed_seq(effects: Iterable[Any]) -> Callable[..., _StreamedScriptResult]:
    """Build a mock ``side_effect`` callable that dispatches over a sequence.

    Each element of ``effects`` is consumed once per call, in order:

    - ``_StreamedSideEffect`` (from :func:`streamed_ok`/:func:`streamed_fail`/
      :func:`streamed_timeout`): the underlying callable is invoked with the
      real call arguments so log-writes and ``on_pid`` behavior are preserved.
    - ``BaseException`` instance: raised, mirroring ``Mock.side_effect`` list
      semantics.

    Using a generator wrapper instead of passing the iterable directly to
    ``side_effect`` lets each ``_StreamedSideEffect`` actually run and
    interact with the ``log_path``/``on_pid`` kwargs.
    """
    iterator = iter(effects)

    def call(*args: object, **kwargs: object) -> _StreamedScriptResult:
        effect = next(iterator)
        if isinstance(effect, BaseException):
            raise effect
        if callable(effect):
            return effect(*args, **kwargs)
        assert isinstance(effect, _StreamedScriptResult)
        return effect

    return call


def single_chop_run_id(lumberjack_name: str, chop_name: str) -> str:
    """Return the single run id recorded for ``chop_name`` under ``lumberjack``."""
    index = read_chop_run_index(lumberjack_name, chop_name)
    assert len(index) == 1, index
    return index[0]
