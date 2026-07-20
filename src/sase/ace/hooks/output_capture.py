"""Bound completed hook-output captures without touching running files."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

COMPLETION_MARKER = b"===HOOK_COMPLETE==="
_ELISION_MARKER = b"=== SASE HOOK OUTPUT ELIDED:"
HOOK_OUTPUT_HEAD_BYTES = 200 * 1024
HOOK_OUTPUT_TAIL_BYTES = 300 * 1024


def compact_completed_hook_output(
    path: Path,
    content: bytes,
    *,
    head_bytes: int = HOOK_OUTPUT_HEAD_BYTES,
    tail_bytes: int = HOOK_OUTPUT_TAIL_BYTES,
) -> bool:
    """Atomically retain a completed capture's byte-budgeted head and tail.

    Returns whether the file was compacted. Missing completion markers, small
    captures, and all filesystem failures are best-effort no-ops.
    """
    if COMPLETION_MARKER not in content:
        return False
    if _ELISION_MARKER in content:
        return False
    if head_bytes < 0 or tail_bytes < 0:
        return False
    if len(content) <= head_bytes + tail_bytes:
        return False

    head = _valid_utf8_prefix(content, head_bytes)
    tail = _valid_utf8_suffix(content, tail_bytes)
    omitted = len(content) - len(head) - len(tail)
    marker = (
        f"\n\n{_ELISION_MARKER.decode()} {omitted} bytes omitted ===\n\n"
    ).encode()
    replacement = head + marker + tail

    temporary_path: Path | None = None
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        fd, temporary = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        _fsync_dir(path.parent)
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        return False
    return True


def _valid_utf8_prefix(content: bytes, limit: int) -> bytes:
    return content[:limit].decode("utf-8", errors="ignore").encode("utf-8")


def _valid_utf8_suffix(content: bytes, limit: int) -> bytes:
    if limit == 0:
        return b""
    return content[-limit:].decode("utf-8", errors="ignore").encode("utf-8")


def _fsync_dir(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


__all__ = [
    "COMPLETION_MARKER",
    "HOOK_OUTPUT_HEAD_BYTES",
    "HOOK_OUTPUT_TAIL_BYTES",
    "compact_completed_hook_output",
]
