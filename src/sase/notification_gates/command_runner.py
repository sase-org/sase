"""Trusted execution primitives shared by gate options and gate actions.

Every gate command — the terminal ones an option runs and the repeatable ones
an action runs — goes through :func:`run_owned_command`, so both share one
trust model: the command's hash is re-verified against the reviewed envelope,
it is started with ``shell=False`` against ``/proc/self/fd/N``, and reviewer
input reaches it as canonical JSON on stdin and never through ``argv``.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.notification_gates.durability import atomic_write_json, canonical_json_bytes
from sase.notification_gates.models import GATE_RESPONSE_SCHEMA_VERSION, GateError
from sase.notification_gates.paths import open_regular_nofollow, owned_resource_path


def run_owned_command(
    bundle_path: Path,
    command_argv: tuple[str, ...],
    *,
    expected_hash: str,
    input_data: object,
    on_output_line: Callable[[str, str], None] | None = None,
    on_process_state: Callable[[subprocess.Popen[bytes], bool], None] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run one hash-verified bundle command with JSON input on its stdin."""
    command_path = owned_resource_path(bundle_path, command_argv[0])
    command_fd = open_regular_nofollow(command_path)
    try:
        if _sha256_fd(command_fd) != expected_hash:
            raise GateError(
                "hash_mismatch",
                command_argv[0],
                "command changed before execution",
            )
        os.lseek(command_fd, 0, os.SEEK_SET)
        argv = (f"/proc/self/fd/{command_fd}", *command_argv[1:])
        try:
            if on_output_line is not None:
                return _run_command_streaming(
                    argv,
                    input_data=canonical_json_bytes(input_data) + b"\n",
                    cwd=bundle_path,
                    pass_fds=(command_fd,),
                    on_output_line=on_output_line,
                    on_process_state=on_process_state,
                )
            return subprocess.run(
                argv,
                input=canonical_json_bytes(input_data) + b"\n",
                capture_output=True,
                cwd=bundle_path,
                pass_fds=(command_fd,),
                shell=False,
                check=False,
            )
        except OSError as exc:
            raise GateError(
                "command_start_failed",
                command_argv[0],
                f"cannot start command: {exc}",
            ) from exc
    finally:
        os.close(command_fd)


def _ignorable_stdin_error(exc: OSError) -> bool:
    """Report whether one stdin error just means the command ignored its input."""
    return isinstance(exc, BrokenPipeError) or exc.errno == errno.EINVAL


def _write_command_stdin(process: subprocess.Popen[bytes], input_data: bytes) -> None:
    """Hand one payload to a command that is free to never read it.

    A command may exit before draining stdin. The buffered writer then raises
    BrokenPipeError from ``flush()`` and, because the payload stays buffered,
    raises it a second time from ``close()``. Both have to be tolerated, exactly
    as ``subprocess.Popen._stdin_write`` does for ``communicate()``.
    """
    assert process.stdin is not None
    try:
        try:
            process.stdin.write(input_data)
            process.stdin.flush()
        except OSError as exc:
            if not _ignorable_stdin_error(exc):
                raise
    finally:
        try:
            process.stdin.close()
        except OSError as exc:
            if not _ignorable_stdin_error(exc):
                raise


def _run_command_streaming(
    argv: tuple[str, ...],
    *,
    input_data: bytes,
    cwd: Path,
    pass_fds: tuple[int, ...],
    on_output_line: Callable[[str, str], None],
    on_process_state: Callable[[subprocess.Popen[bytes], bool], None] | None,
) -> subprocess.CompletedProcess[bytes]:
    """Run one trusted gate command while streaming both output channels."""
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        pass_fds=pass_fds,
        shell=False,
    )
    if on_process_state is not None:
        on_process_state(process, True)

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    def drain(stream: Any, chunks: list[bytes], stream_name: str) -> None:
        for chunk in iter(stream.readline, b""):
            chunks.append(chunk)
            line = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
            if line:
                on_output_line(stream_name, line)

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_thread = threading.Thread(
        target=drain,
        args=(process.stdout, stdout_chunks, "stdout"),
        name=f"sase-gate-stdout-{process.pid}",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=drain,
        args=(process.stderr, stderr_chunks, "stderr"),
        name=f"sase-gate-stderr-{process.pid}",
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    try:
        try:
            _write_command_stdin(process, input_data)
        except BaseException:
            process.kill()
            raise
        finally:
            returncode = process.wait()
            stdout_thread.join()
            stderr_thread.join()
    finally:
        if on_process_state is not None:
            on_process_state(process, False)
    return subprocess.CompletedProcess(
        argv,
        returncode,
        stdout=b"".join(stdout_chunks),
        stderr=b"".join(stderr_chunks),
    )


def reject_command_terminal_state(
    response_path: Path,
    cancellation_path: Path,
    *,
    target: str,
) -> None:
    """Refuse a command that wrote a terminal file, and remove what it wrote."""
    if not response_path.exists() and not cancellation_path.exists():
        return
    _remove_untrusted_terminal(response_path)
    _remove_untrusted_terminal(cancellation_path)
    raise GateError(
        "terminal_state_changed",
        target,
        "command may not create response.json or cancellation.json",
    )


def _remove_untrusted_terminal(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def decode_json_result(value: bytes) -> Any:
    """Decode one command's stdout as a single JSON value."""
    return json.loads(value)


def decode_output(value: bytes, *, limit: int = 16_384) -> str:
    """Render bounded command output for an error record."""
    return value[:limit].decode("utf-8", errors="replace").strip()


def validate_json_instance(value: object, schema: dict[str, Any], target: str) -> None:
    """Validate one JSON value against a declared schema, or raise."""
    try:
        from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

        Draft202012Validator(schema).validate(value)
    except Exception as exc:
        raise GateError("schema_validation_failed", target, str(exc)) from exc


def record_execution_error(
    bundle_path: Path,
    *,
    option_id: str,
    code: str,
    message: str,
    source: str,
    returncode: int | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
) -> None:
    """Write one diagnosable failure record a reviewer can read with ``d``."""
    errors = bundle_path / "errors"
    payload = {
        "schema_version": GATE_RESPONSE_SCHEMA_VERSION,
        "option_id": option_id,
        "code": code,
        "message": message,
        "source": source,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "created_at_unix": time.time(),
    }
    atomic_write_json(errors / f"{time.time_ns()}-{uuid4().hex}.json", payload)


@contextmanager
def recorded_rejection(
    bundle_path: Path,
    option_id: str,
    source: str,
    *,
    message_transform: Callable[[str], str] | None = None,
) -> Iterator[None]:
    """Write a pre-execution rejection to ``errors/`` before it propagates.

    Input-schema, bounds, feedback, and adapter-selection failures all happen
    before the first command runs, so without this they leave no trace and a
    reviewer pressing ``d`` sees nothing at all.

    Every rejection is recorded, not only :class:`GateError`: an adapter
    rejects with its own type -- the plan adapter raises
    ``PlanApprovalValidationError`` from ``validate_edited_resource`` -- and a
    narrower clause let exactly those rejections reach the reviewer with an
    empty ``errors/``. The exception itself normally propagates unchanged so
    callers that discriminate on the adapter's own type still can. When
    ``message_transform`` sanitizes a :class:`GateError`, a replacement with
    the same code and target propagates so its raw message does not escape
    through the caller either.
    """
    try:
        yield
    except Exception as exc:
        raw_message = str(exc)
        message = (
            raw_message if message_transform is None else message_transform(raw_message)
        )
        record_execution_error(
            bundle_path,
            option_id=option_id,
            code=exc.code if isinstance(exc, GateError) else "adapter_rejected",
            message=message,
            source=source,
        )
        if isinstance(exc, GateError) and message != raw_message:
            raise GateError(exc.code, exc.target, message) from None
        raise


def _sha256_fd(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        block = os.read(fd, 1024 * 1024)
        if not block:
            break
        digest.update(block)
    return digest.hexdigest()


__all__ = [
    "decode_json_result",
    "decode_output",
    "record_execution_error",
    "recorded_rejection",
    "reject_command_terminal_state",
    "run_owned_command",
    "validate_json_instance",
]
