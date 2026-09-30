"""TTY progress for attachment ingest, upload, and download.

A Rich progress bar renders on stderr for transfers above 8 MiB on a TTY;
agents (``SASE_AGENT`` set) and pipes get only the final echo line. The
bar is transient: it disappears when the transfer finishes, leaving the
write echo as the durable record.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any

from sase.bead.attachments.blob_store import ProgressCallback

PROGRESS_MIN_BYTES = 8 * 1024 * 1024
"""Transfers below this size never draw a bar; the echo line is enough."""

ProgressFactory = Callable[[str, int | None], AbstractContextManager[Any]]
"""Build a bar context for ``(label, total_bytes)``; yields a callback or None."""


def _progress_allowed(size_bytes: int | None) -> bool:
    """Return whether a transfer of *size_bytes* may draw a progress bar."""
    if size_bytes is None or size_bytes < PROGRESS_MIN_BYTES:
        return False
    try:
        if not sys.stderr.isatty():
            return False
    except Exception:
        return False
    if os.environ.get("SASE_AGENT"):
        return False
    return True


@contextlib.contextmanager
def transfer_progress(
    label: str,
    total_bytes: int | None,
) -> Iterator[ProgressCallback | None]:
    """Yield a progress callback, or None when no bar should draw.

    *label* names the transfer (the attachment name); *total_bytes* sizes
    the bar when known. The callback accepts ``(bytes_done, total_or_None)``
    per the :class:`BlobStore` protocol. Exiting stops a live bar.
    """
    if not _progress_allowed(total_bytes):
        yield None
        return
    try:
        from rich.progress import (
            BarColumn,
            DownloadColumn,
            Progress,
            TextColumn,
            TransferSpeedColumn,
        )
    except Exception:
        yield None
        return
    progress: Any = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        transient=True,
        console=None,
    )
    total = total_bytes if total_bytes and total_bytes > 0 else None
    try:
        progress.start()
        task = progress.add_task(label, total=total)
    except Exception:
        with contextlib.suppress(Exception):
            progress.stop()
        yield None
        return

    def _callback(done: int, total_or_none: int | None) -> None:
        try:
            if total_or_none and total_or_none > 0 and total_or_none != total:
                progress.update(task, total=total_or_none)
            progress.update(task, completed=done)
        except Exception:
            pass

    try:
        yield _callback
    finally:
        with contextlib.suppress(Exception):
            progress.stop()


__all__ = [
    "PROGRESS_MIN_BYTES",
    "ProgressFactory",
    "_progress_allowed",
    "transfer_progress",
]
