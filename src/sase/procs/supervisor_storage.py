"""Storage-failure handling for supervisor I/O and settlement."""

from __future__ import annotations

import errno
import os
import sys
import time

from .models import Proc
from .runtime import proc_runtime_dir
from .settlement import settle_named_proc
from .spawn import SUPERVISOR_LOG_NAME

# Stay alive through an hourly housekeeping pass, with bounded retry traffic.
_SETTLEMENT_RETRY_SECONDS = 70 * 60.0
_MAX_RETRY_DELAY_SECONDS = 60.0
_ERROR_TAIL_BYTES = 4096
_ERROR_LINE_CHARS = 500


def settle_with_storage_retry(
    proc_id: str,
    *,
    supervisor_id: str,
    status: str,
    message: str,
    termination_reason: str,
    exit_code: int | None = None,
) -> Proc:
    """Retry exhausted storage while retaining the observed command outcome."""
    deadline = time.monotonic() + _SETTLEMENT_RETRY_SECONDS
    delay = 1.0
    while True:
        try:
            # Settlement freezes the first outcome and resumes durable checkpoints.
            # A retry must pass that same observation, never supervisor-loss.
            return settle_named_proc(
                proc_id,
                supervisor_id=supervisor_id,
                status=status,
                message=message,
                termination_reason=termination_reason,
                exit_code=exit_code,
            )
        except (OSError, ValueError) as exc:
            if not _storage_exhausted(exc):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            pause = min(delay, remaining)
            line = " ".join(str(exc).splitlines())
            try:
                print(
                    f"proc {proc_id}: settlement storage exhausted; "
                    f"retrying in {pause:g}s: {line}",
                    file=sys.stderr,
                    flush=True,
                )
            except (OSError, ValueError):
                pass
            time.sleep(pause)
            delay = min(delay * 2, _MAX_RETRY_DELAY_SECONDS)


def _storage_exhausted(exc: OSError | ValueError) -> bool:
    if isinstance(exc, OSError):
        return exc.errno in {errno.ENOSPC, errno.EDQUOT}
    return any(f"os error {code}" in str(exc) for code in (errno.ENOSPC, errno.EDQUOT))


def last_supervisor_error(proc_id: str) -> str | None:
    """Read a bounded, single-line diagnostic from the supervisor's stderr."""
    try:
        path = proc_runtime_dir(proc_id) / SUPERVISOR_LOG_NAME
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - _ERROR_TAIL_BYTES))
            tail = handle.read(_ERROR_TAIL_BYTES)
    except OSError:
        return None
    lines = tail.decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        line = " ".join(line.split())
        if line:
            disk_full = (
                "os error 28" in line or "no space left on device" in line.lower()
            )
            # Retain the end of an oversized exception line, where its cause lives.
            if len(line) > _ERROR_LINE_CHARS:
                line = "…" + line[-(_ERROR_LINE_CHARS - 1) :]
            return f"{line} (disk full)" if disk_full else line
    return None
