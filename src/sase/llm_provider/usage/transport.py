"""Bounded JSON-line process transport for usage collectors."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_MAX_LINE_BYTES = 1_048_576
DEFAULT_MAX_TOTAL_BYTES = 8_388_608
DEFAULT_MAX_STDERR_BYTES = 65_536
TERMINATE_GRACE_SECONDS = 0.4
UNSERVICED_REQUEST_METHODS = frozenset(
    {
        "login",
        "auth",
        "token/refresh",
        "tools/call",
        "approval",
        "session/new",
        "turn/start",
    }
)


class JsonLineTransportError(RuntimeError):
    """A JSON-line session failed without a correlated response."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class JsonLineSession:
    """Killable argv-only child speaking bounded JSON lines over stdio.

    JSON-RPC and ACP handshakes stay in collectors. This type only correlates
    response ids, skips notifications, bounds output, and never services
    unsolicited requests.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        deadline_at: float,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        max_stderr_bytes: int = DEFAULT_MAX_STDERR_BYTES,
    ) -> None:
        self._deadline_at = deadline_at
        self._max_line_bytes = max_line_bytes
        self._max_total_bytes = max_total_bytes
        self._max_stderr_bytes = max_stderr_bytes
        self._stdout_total = 0
        self._stderr_total = 0
        self._stdout_buf = bytearray()
        self._stderr = bytearray()
        self._closed = False
        self.process = spawn_killable_process(argv, cwd=cwd, env=env)

    @property
    def stderr_text(self) -> str:
        """Return collected stderr with replacement decoding."""
        return self._stderr.decode("utf-8", errors="replace")

    def send(self, payload: Mapping[str, Any]) -> None:
        """Write one JSON line to stdin."""
        if self.process.stdin is None:
            raise JsonLineTransportError("stdin_closed", "process stdin is closed")
        line = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        self.process.stdin.write(line)
        self.process.stdin.flush()

    def read_response(self, request_id: object) -> dict[str, Any]:
        """Return the JSON object whose ``id`` matches *request_id*."""
        try:
            while True:
                line = self._read_line()
                try:
                    decoded = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise JsonLineTransportError(
                        "malformed_response", "JSON-line response was malformed"
                    ) from exc
                if not isinstance(decoded, dict):
                    raise JsonLineTransportError(
                        "malformed_response", "JSON-line response was not an object"
                    )
                method = decoded.get("method")
                if isinstance(method, str) and "id" in decoded:
                    raise JsonLineTransportError(
                        "unsolicited_request",
                        _unsolicited_message(method),
                    )
                if isinstance(method, str):
                    continue
                if decoded.get("id") == request_id:
                    return decoded
        except JsonLineTransportError:
            self.close()
            raise

    def close_stdin(self) -> None:
        """Close stdin so the child sees EOF."""
        stdin = self.process.stdin
        if stdin is None:
            return
        try:
            stdin.close()
        except OSError:
            return
        self.process.stdin = None

    def close(self) -> None:
        """Terminate and reap the owned process tree."""
        if self._closed:
            return
        self._closed = True
        self.close_stdin()
        _terminate_process_tree(self.process)

    def __enter__(self) -> JsonLineSession:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _read_line(self) -> str:
        stdout = self.process.stdout
        if stdout is None:
            raise JsonLineTransportError("eof", "process stdout closed")
        while True:
            newline_at = self._stdout_buf.find(b"\n")
            if newline_at != -1:
                raw = bytes(self._stdout_buf[:newline_at])
                del self._stdout_buf[: newline_at + 1]
                if len(raw) > self._max_line_bytes:
                    raise JsonLineTransportError(
                        "stdout_overflow", "JSON-line output exceeded the line bound"
                    )
                return raw.decode("utf-8", errors="replace")
            if len(self._stdout_buf) > self._max_line_bytes:
                raise JsonLineTransportError(
                    "stdout_overflow", "JSON-line output exceeded the line bound"
                )
            self._pump(require_stdout=True)

    def _pump(self, *, require_stdout: bool) -> None:
        remaining = self._deadline_at - time.time()
        if remaining <= 0:
            raise JsonLineTransportError(
                "timeout", "JSON-line session exceeded deadline"
            )
        stdout = self.process.stdout
        stderr = self.process.stderr
        watch: list[Any] = []
        if stdout is not None:
            watch.append(stdout)
        if stderr is not None:
            watch.append(stderr)
        if not watch:
            raise JsonLineTransportError("eof", "process streams closed")
        ready, _, _ = select.select(watch, [], [], min(remaining, 0.1))
        if stdout is not None and stdout in ready:
            chunk = stdout.read(4096)
            if chunk:
                self._stdout_total += len(chunk)
                if self._stdout_total > self._max_total_bytes:
                    raise JsonLineTransportError(
                        "stdout_overflow",
                        "JSON-line output exceeded the total bound",
                    )
                self._stdout_buf.extend(chunk)
            elif require_stdout and self.process.poll() is not None:
                raise JsonLineTransportError("eof", "process ended before a response")
        if stderr is not None and stderr in ready:
            chunk = stderr.read(4096)
            if chunk:
                self._stderr_total += len(chunk)
                if self._stderr_total > self._max_stderr_bytes:
                    raise JsonLineTransportError(
                        "stderr_overflow",
                        "JSON-line stderr exceeded the bound",
                    )
                self._stderr.extend(chunk)
        if require_stdout and not ready and self.process.poll() is not None:
            raise JsonLineTransportError("eof", "process ended before a response")


def spawn_killable_process(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.Popen[bytes]:
    """Start an argv-only child in its own process group."""
    return subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        start_new_session=True,
    )


def bounded_communicate(
    process: subprocess.Popen[bytes],
    stdin_payload: bytes,
    *,
    deadline_at: float,
    max_stdout_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_stderr_bytes: int = DEFAULT_MAX_STDERR_BYTES,
) -> tuple[bytes, bytes, str | None]:
    """Write *stdin_payload*, close stdin, and read bounded stdout/stderr."""
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    if process.stdin is not None:
        try:
            process.stdin.write(stdin_payload)
            process.stdin.close()
        except OSError:
            pass
        process.stdin = None
    overflow: str | None = None
    while True:
        remaining = deadline_at - time.time()
        if remaining <= 0:
            overflow = overflow or "timeout"
            break
        watch: list[Any] = []
        if process.stdout is not None:
            watch.append(process.stdout)
        if process.stderr is not None:
            watch.append(process.stderr)
        if not watch:
            break
        ready, _, _ = select.select(watch, [], [], min(remaining, 0.1))
        if process.stdout is not None and process.stdout in ready:
            chunk = process.stdout.read(4096)
            if chunk:
                stdout_buf.extend(chunk)
                if len(stdout_buf) > max_stdout_bytes:
                    overflow = "stdout_overflow"
                    break
            else:
                process.stdout = None
        if process.stderr is not None and process.stderr in ready:
            chunk = process.stderr.read(4096)
            if chunk:
                stderr_buf.extend(chunk)
                if len(stderr_buf) > max_stderr_bytes:
                    overflow = "stderr_overflow"
                    break
            else:
                process.stderr = None
        if process.poll() is not None and not ready:
            break
    _terminate_process_tree(process)
    return bytes(stdout_buf), bytes(stderr_buf), overflow


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """SIGTERM then SIGKILL the child's process group and reap it."""
    pid = process.pid
    if pid and process.poll() is None:
        _signal_group(pid, signal.SIGTERM)
        deadline = time.time() + TERMINATE_GRACE_SECONDS
        while process.poll() is None and time.time() < deadline:
            time.sleep(0.02)
        if process.poll() is None:
            _signal_group(pid, signal.SIGKILL)
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        if pid:
            _signal_group(pid, signal.SIGKILL)
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


def _signal_group(pid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        return
    except OSError:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return


def _unsolicited_message(method: str) -> str:
    if method in UNSERVICED_REQUEST_METHODS or method.split("/", 1)[0] in {
        "login",
        "auth",
        "tools",
        "approval",
    }:
        return "refusing unsolicited provider request"
    return "refusing unsolicited JSON-line request"
