"""Streaming proc reporting and subprocess helpers for ACE background procs."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from .proc_queue import ProcInfo, ProcLogStream

if TYPE_CHECKING:
    from sase.uv_tool.runner import UvChangeSet

LineCallback = Callable[[str], None]
RunOutputTarget = Literal["stdout", "stderr"]


def command_display(argv: Sequence[object]) -> str:
    """Return a shell-like command string for display only."""
    return shlex.join(str(part) for part in argv)


def _stream_subprocess(
    argv: Sequence[object],
    *,
    on_line: LineCallback,
    cancel_event: threading.Event,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    proc_info: ProcInfo | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run *argv* while streaming combined stdout/stderr lines to *on_line*."""
    args = [str(part) for part in argv]
    started = time.monotonic()
    output_chunks: list[str] = []
    output_lock = threading.Lock()
    timed_out = False
    cancelled = False

    process = subprocess.Popen(
        args,
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    if proc_info is not None:
        proc_info.register_process(process)

    def _read_output() -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            with output_lock:
                output_chunks.append(raw)
            on_line(raw.rstrip("\r\n"))

    reader = threading.Thread(
        target=_read_output,
        name=f"sase-proc-output-{process.pid}",
        daemon=True,
    )
    reader.start()

    try:
        while process.poll() is None:
            if cancel_event.is_set():
                cancelled = True
                _terminate_process_group(process)
                break
            if timeout is not None and time.monotonic() - started > timeout:
                timed_out = True
                _terminate_process_group(process)
                break
            time.sleep(0.05)

        if timed_out or cancelled:
            _wait_then_kill(process)
        returncode = process.wait()
    finally:
        reader.join(timeout=1.0)
        if proc_info is not None:
            proc_info.unregister_process(process)

    with output_lock:
        output = "".join(output_chunks)
    if timed_out:
        assert timeout is not None
        raise subprocess.TimeoutExpired(args, timeout, output=output)
    return subprocess.CompletedProcess(args, returncode, stdout=output, stderr="")


@dataclass(frozen=True)
class ProcReporter:
    """Small reporting handle passed into tracked proc bodies."""

    proc_info: ProcInfo

    def phase(self, label: str) -> None:
        """Set the high-level proc phase and append a visible marker line."""
        self.proc_info.phase = label
        self.log(f"==> {label}", stream="progress")

    def section(self, title: str) -> None:
        """Append a visual divider for multi-step proc output."""
        self.log(f"--- {title}", stream="header")

    def log(self, text: str, *, stream: ProcLogStream = "stdout") -> None:
        """Append text to this proc's log."""
        self.proc_info.log.append(text, stream=stream)

    def set_command(self, argv: Sequence[object]) -> None:
        """Set the command displayed in the proc header."""
        self.proc_info.command = [str(part) for part in argv]
        self.proc_info.log.append(f"$ {command_display(argv)}", stream="header")

    def run(
        self,
        argv: Sequence[object],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        stream: ProcLogStream = "stdout",
    ) -> subprocess.CompletedProcess[str]:
        """Run a subprocess with live line streaming into this proc."""
        self.set_command(argv)
        result = _stream_subprocess(
            argv,
            on_line=lambda line: self.log(line, stream=stream),
            cancel_event=self.proc_info.cancel_event,
            cwd=cwd,
            env=env,
            timeout=timeout,
            proc_info=self.proc_info,
        )
        self.proc_info.exit_code = result.returncode
        return result

    def subprocess_run_fn(
        self, *, output_target: RunOutputTarget = "stdout"
    ) -> Callable[..., subprocess.CompletedProcess[str]]:
        """Return a ``subprocess.run``-shaped function backed by ``run``."""

        def _run(
            argv: Sequence[object],
            *,
            capture_output: bool = True,
            text: bool = True,
            timeout: float | None = None,
            cwd: str | Path | None = None,
            env: Mapping[str, str] | None = None,
            check: bool = False,
            **_kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            del capture_output, text
            completed = self.run(argv, cwd=cwd, env=env, timeout=timeout)
            if output_target == "stderr":
                completed = subprocess.CompletedProcess(
                    completed.args,
                    completed.returncode,
                    stdout="",
                    stderr=completed.stdout,
                )
            if check and completed.returncode != 0:
                raise subprocess.CalledProcessError(
                    completed.returncode,
                    completed.args,
                    output=completed.stdout,
                    stderr=completed.stderr,
                )
            return completed

        return _run

    def uv_runner(self) -> Callable[[list[str]], UvChangeSet]:
        """Return a ``run_uv``-shaped callable with live uv output streaming."""
        from sase.uv_tool.runner import run_uv

        def _run(argv: list[str]) -> UvChangeSet:
            return run_uv(
                argv,
                run_fn=self.subprocess_run_fn(output_target="stderr"),
            )

        return _run


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.terminate()
        except ProcessLookupError:
            return


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.kill()
        except ProcessLookupError:
            return


def _wait_then_kill(process: subprocess.Popen[str]) -> None:
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
