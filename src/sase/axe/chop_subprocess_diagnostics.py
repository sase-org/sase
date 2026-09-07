"""Capture bounded subprocess diagnostics for failed AXE chop runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.axe_chop_facade import (
    CHOP_ENGINE_SCHEMA_VERSION,
    normalize_chop_subprocess_diagnostic,
)

from .state import chop_run_log_path

SUBPROCESS_DIAGNOSTIC_LOG_READ_BYTES = 64 * 1024


def capture_chop_subprocess_diagnostic(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    exit_code: int | None,
) -> dict[str, Any]:
    """Read a bounded output sample and delegate diagnostic shaping to Rust."""

    log_path = chop_run_log_path(lumberjack_name, chop_name, run_id)
    output: str | None = None
    output_status = "unavailable"
    unavailable_reason: str | None = "missing_log"
    input_omitted_bytes = 0
    had_decode_errors = False

    raw = _read_log_tail_bytes(log_path)
    if raw.error is None:
        output = _decode_output(raw.data)
        had_decode_errors = raw.had_decode_errors
        output_status = "captured" if raw.data else "absent"
        unavailable_reason = None
        input_omitted_bytes = raw.omitted_bytes
    else:
        unavailable_reason = raw.error

    return normalize_chop_subprocess_diagnostic(
        {
            "schema_version": CHOP_ENGINE_SCHEMA_VERSION,
            "run_id": run_id,
            "exit_code": exit_code,
            "source_log_path": str(log_path),
            "output": output,
            "output_status": output_status,
            "unavailable_reason": unavailable_reason,
            "input_omitted_bytes": input_omitted_bytes,
            "had_decode_errors": had_decode_errors,
        }
    )


class _LogTailBytes:
    def __init__(
        self,
        *,
        data: bytes = b"",
        omitted_bytes: int = 0,
        had_decode_errors: bool = False,
        error: str | None = None,
    ) -> None:
        self.data = data
        self.omitted_bytes = omitted_bytes
        self.had_decode_errors = had_decode_errors
        self.error = error


def _read_log_tail_bytes(log_path: Path) -> _LogTailBytes:
    try:
        file_size = log_path.stat().st_size
    except FileNotFoundError:
        return _LogTailBytes(error="missing_log")
    except OSError as exc:
        return _LogTailBytes(error=f"{type(exc).__name__}: {exc}")

    read_size = min(file_size, SUBPROCESS_DIAGNOSTIC_LOG_READ_BYTES)
    omitted_bytes = max(0, file_size - read_size)
    if read_size <= 0:
        return _LogTailBytes(data=b"", omitted_bytes=omitted_bytes)

    try:
        with open(log_path, "rb") as file:
            file.seek(file_size - read_size)
            data = file.read(read_size)
    except FileNotFoundError:
        return _LogTailBytes(error="missing_log")
    except OSError as exc:
        return _LogTailBytes(error=f"{type(exc).__name__}: {exc}")

    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return _LogTailBytes(
            data=data,
            omitted_bytes=omitted_bytes,
            had_decode_errors=True,
        )
    return _LogTailBytes(data=data, omitted_bytes=omitted_bytes)


def _decode_output(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


__all__ = [
    "SUBPROCESS_DIAGNOSTIC_LOG_READ_BYTES",
    "capture_chop_subprocess_diagnostic",
]
