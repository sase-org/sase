"""Presentation-only live reporting for session-local ACE procs.

Session workers publish bounded progress through :class:`ObservedProc` and
:class:`ObservedProcLog`. This handle must not import proc-store mutation APIs,
manufacture durable rows, or revive ``ProcReporter`` / ``ProcQueue``.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ._proc_observer_log import ProcLogStream
from ._proc_observer_models import ObservedProc
from .proc_subprocess import command_display

if TYPE_CHECKING:
    from sase.agent_clis.runner import CommandResult
    from sase.dev_update.models import DevCommandResult
    from sase.uv_tool.runner import UvChangeSet

LineCallback = Callable[[str], None]
RunOutputTarget = Literal["stdout", "stderr"]


def _stream_subprocess(
    argv: Sequence[object],
    *,
    on_line: LineCallback,
    cancel_event: threading.Event,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
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
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    def _read_output() -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            with output_lock:
                output_chunks.append(raw)
            on_line(raw.rstrip("\r\n"))

    reader = threading.Thread(
        target=_read_output,
        name=f"sase-session-proc-output-{process.pid}",
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

    with output_lock:
        output = "".join(output_chunks)
    if timed_out:
        assert timeout is not None
        raise subprocess.TimeoutExpired(args, timeout, output=output)
    return subprocess.CompletedProcess(args, returncode, stdout=output, stderr="")


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


@dataclass(frozen=True)
class SessionProcReporter:
    """Reporting handle passed into session-local worker bodies."""

    proc: ObservedProc
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def phase(self, label: str) -> None:
        """Set the high-level proc phase and append a visible marker line."""
        self.proc.phase = label
        self.log(f"==> {label}", stream="progress")

    def section(self, title: str) -> None:
        """Append a visual divider for multi-step proc output."""
        self.log(f"--- {title}", stream="header")

    def log(self, text: str, *, stream: ProcLogStream = "stdout") -> None:
        """Append text to this proc's bounded presentation log."""
        self.proc.log.append(text, stream=stream)

    def set_command(self, argv: Sequence[object]) -> None:
        """Record the current child command in row metadata and the log."""
        self.proc.command = [str(part) for part in argv]
        self.log(f"$ {command_display(argv)}", stream="header")

    def run(
        self,
        argv: Sequence[object],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        stream: ProcLogStream = "stdout",
        log_lines: bool = True,
        on_line: LineCallback | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a subprocess with live line streaming into this proc.

        ``log_lines=False`` still captures stdout on the returned
        ``CompletedProcess`` but does not append child lines to the proc log
        (used for JSON check payloads). ``on_line`` is invoked on the reader
        thread after optional logging; exceptions there are reported once and
        must not abort the rest of the stream.
        """
        self.set_command(argv)
        hook_failed = False

        def _handle_line(line: str) -> None:
            nonlocal hook_failed
            if log_lines:
                self.log(line, stream=stream)
            if on_line is None:
                return
            try:
                on_line(line)
            except Exception as exc:  # noqa: BLE001 - reader thread must survive.
                if hook_failed:
                    return
                hook_failed = True
                self.log(f"on_line callback failed: {exc}", stream="stderr")

        result = _stream_subprocess(
            argv,
            on_line=_handle_line,
            cancel_event=self.cancel_event,
            cwd=cwd,
            env=env,
            timeout=timeout,
        )
        self.proc.exit_code = result.returncode
        return result

    def subprocess_run_fn(
        self, *, output_target: RunOutputTarget = "stdout"
    ) -> Callable[..., subprocess.CompletedProcess[str]]:
        """Return a ``subprocess.run``-shaped function backed by :meth:`run`."""

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

    def command_runner(self) -> Callable[..., CommandResult]:
        """Return a ``run_command``-shaped agent-CLI runner."""
        from sase.agent_clis.runner import run_command

        def _run(
            argv: Sequence[str],
            *,
            timeout: float = 300.0,
            env_overlay: Mapping[str, str] | None = None,
        ) -> CommandResult:
            return run_command(
                argv,
                timeout=timeout,
                env_overlay=env_overlay,
                run_fn=self.subprocess_run_fn(),
            )

        return _run

    def dev_command_runner(self) -> Callable[..., DevCommandResult]:
        """Return a dev-update command runner that streams into this proc."""
        from sase.dev_update.models import DevCommandResult

        def _run(
            argv: Sequence[str],
            *,
            cwd: Path | None = None,
            env: Mapping[str, str] | None = None,
        ) -> DevCommandResult:
            self.phase("Running " + " ".join(str(part) for part in argv[:2]))
            try:
                completed = self.run(argv, cwd=cwd, env=env)
            except FileNotFoundError as exc:
                return DevCommandResult(returncode=127, stderr=str(exc))
            except subprocess.TimeoutExpired:
                return DevCommandResult(returncode=124, stderr="command timed out")
            except OSError as exc:
                return DevCommandResult(returncode=1, stderr=str(exc))
            return DevCommandResult(
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )

        return _run


__all__ = ["SessionProcReporter"]
