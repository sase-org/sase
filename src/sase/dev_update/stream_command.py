"""Line-streaming subprocess primitive for live progress.

``run_streaming`` runs a child with its output drained by two pump threads so
long-running commands (cargo, uv) can stream each finished line to an
``on_line`` sink while still returning a :class:`subprocess.CompletedProcess`
compatible with :func:`sase.git_lock_retry.run_with_git_lock_retry`.
"""

from __future__ import annotations

import codecs
import os
import re
import signal
import subprocess
import threading
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

#: Grace period after SIGTERM before a timed-out group is SIGKILLed.
_TERMINATE_GRACE_SECONDS = 1.0

#: Grace period after SIGINT before an interrupted group is SIGKILLed.
_INTERRUPT_GRACE_SECONDS = 2.0

#: Poll interval for the wait loop so pump-thread KeyboardInterrupts surface.
_WAIT_POLL_SECONDS = 0.05

_ANSI_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ANSI_ESC_RE = re.compile(r"\x1b[@-Z\\-_]")

#: Callback receiving ``(stream, line)`` where stream is ``"stdout"``/``"stderr"``.
OnLineCallback = Callable[[str, str], None]


def sanitize_line(line: str) -> str:
    """Return *line* without ANSI/OSC escapes or control characters.

    ``[red]``-style literal text is preserved; only real escape sequences
    and Unicode ``Cc`` controls (other than tab) are removed.
    """
    text = _ANSI_OSC_RE.sub("", line)
    text = _ANSI_CSI_RE.sub("", text)
    text = _ANSI_ESC_RE.sub("", text)
    kept: list[str] = []
    for char in text:
        if char == "\t":
            kept.append(char)
            continue
        if unicodedata.category(char) == "Cc":
            continue
        kept.append(char)
    return "".join(kept)


def run_streaming(
    argv: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    stdin: int | Any | None = None,
    timeout: float | None = None,
    on_line: OnLineCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run *argv*, streaming each finished stdout/stderr line to *on_line*.

    Output is accumulated unsanitized and returned as a
    :class:`subprocess.CompletedProcess[str]`. ``on_line`` receives
    ``(stream, sanitized_line)``; a raising callback is disabled after its
    first failure so progress can never break a command, except
    ``KeyboardInterrupt``/``SystemExit`` which terminate the process group
    and propagate.
    """
    args = list(argv)
    child_env = _child_env(env)
    process = subprocess.Popen(
        args,
        cwd=str(cwd) if cwd is not None else None,
        env=child_env,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        start_new_session=True,
    )
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    state = _CallbackState(on_line)
    threads: list[threading.Thread] = []
    if process.stdout is not None:
        threads.append(_start_pump(process.stdout, "stdout", state, stdout_chunks))
    if process.stderr is not None:
        threads.append(_start_pump(process.stderr, "stderr", state, stderr_chunks))
    try:
        returncode = _wait_process(process, state, timeout)
    except _StreamingTimeout as exc:
        _terminate_process_group(process)
        try:
            process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            try:
                process.wait(timeout=_TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        _join_pumps(threads)
        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)
        raise subprocess.TimeoutExpired(
            args,
            exc.timeout,
            output=stdout_text,
            stderr=stderr_text,
        ) from None
    except BaseException:
        _interrupt_process_group(process)
        _join_pumps(threads)
        raise
    _join_pumps(threads)
    pending = state.take_pending()
    if pending is not None:
        _interrupt_process_group(process)
        raise pending
    return subprocess.CompletedProcess(
        args,
        returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
    )


class _StreamingTimeout(Exception):
    def __init__(self, timeout: float) -> None:
        super().__init__(timeout)
        self.timeout = timeout


class _CallbackState:
    """Thread-safe wrapper that disables a failing ``on_line`` sink."""

    def __init__(self, callback: OnLineCallback | None) -> None:
        self._callback = callback
        self._lock = threading.Lock()
        self._disabled = False
        self._pending: BaseException | None = None

    def __call__(self, stream: str, line: str) -> None:
        with self._lock:
            if self._disabled or self._callback is None:
                return
            callback = self._callback
        try:
            callback(stream, line)
        except (KeyboardInterrupt, SystemExit) as exc:
            with self._lock:
                self._disabled = True
                if self._pending is None:
                    self._pending = exc
        except Exception:  # noqa: BLE001 - progress must never break a command.
            with self._lock:
                self._disabled = True
        except BaseException as exc:  # noqa: BLE001 - e.g. CancelledError stays fatal.
            with self._lock:
                self._disabled = True
                if self._pending is None and not isinstance(exc, Exception):
                    self._pending = exc

    def take_pending(self) -> BaseException | None:
        with self._lock:
            pending = self._pending
            self._pending = None
            return pending

    def has_pending(self) -> bool:
        with self._lock:
            return self._pending is not None


def _child_env(env: Mapping[str, str] | None) -> dict[str, str]:
    merged = dict(os.environ)
    if env is not None:
        merged.update(env)
    merged.setdefault("PYTHONUNBUFFERED", "1")
    return merged


def _start_pump(
    stream: Any,
    name: str,
    callback: _CallbackState,
    chunks: list[str],
) -> threading.Thread:
    thread = threading.Thread(
        target=_pump_stream,
        args=(stream, name, callback, chunks),
        daemon=True,
    )
    thread.start()
    return thread


def _pump_stream(
    stream: Any,
    name: str,
    callback: _CallbackState,
    chunks: list[str],
) -> None:
    blocker = getattr(signal, "pthread_sigmask", None)
    if blocker is not None:
        try:
            blocker(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
        except (OSError, ValueError):
            pass
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buf = ""
    # Use read1 (return as soon as any data is available) so lines stream
    # live; plain read() would block until the buffer fills or EOF.
    reader = getattr(stream, "read1", stream.read)
    try:
        while True:
            data = reader(4096)
            if not data:
                break
            text = decoder.decode(data, final=False)
            if not text:
                continue
            chunks.append(text)
            buf += text
            while "\n" in buf:
                raw_line, buf = buf.split("\n", 1)
                collapsed = raw_line.split("\r")[-1]
                callback(name, sanitize_line(collapsed))
        tail = decoder.decode(b"", final=True)
        if tail:
            chunks.append(tail)
            buf += tail
        if buf:
            collapsed = buf.split("\r")[-1]
            if collapsed:
                callback(name, sanitize_line(collapsed))
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _wait_process(
    process: subprocess.Popen[bytes],
    state: _CallbackState,
    timeout: float | None,
) -> int:
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        if state.has_pending():
            pending = state.take_pending()
            assert pending is not None
            raise pending
        try:
            return process.wait(timeout=_WAIT_POLL_SECONDS)
        except subprocess.TimeoutExpired:
            if deadline is not None and time.monotonic() >= deadline:
                raise _StreamingTimeout(
                    timeout if timeout is not None else 0.0
                ) from None
            continue


def _join_pumps(threads: list[threading.Thread]) -> None:
    for thread in threads:
        thread.join()


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.terminate()
        except (ProcessLookupError, OSError):
            return


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.kill()
        except (ProcessLookupError, OSError):
            return


def _interrupt_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.send_signal(signal.SIGINT)
        except (ProcessLookupError, OSError):
            return
    try:
        process.wait(timeout=_INTERRUPT_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        try:
            process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass


__all__ = ["OnLineCallback", "run_streaming", "sanitize_line"]
