"""Fail filesystem metadata calls made on the main thread inside a block.

Phase ``ui_io_offload`` (sase-1tz.2.1.11) asserts that TUI ticks and handlers
do no filesystem I/O on the main thread. :func:`main_thread_fs_guard` patches
``os.stat``, ``os.lstat``, ``os.scandir``, and :meth:`pathlib.Path.resolve`
so that calls from the entering thread are recorded and raise, while worker
threads keep the real behavior. Callers that swallow exceptions still show
up in the returned list, so tests assert on it rather than on the raise.
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock


class MainThreadFsViolation(AssertionError):
    """Raised for a guarded filesystem call made on the entering thread."""


def _guarded(
    name: str,
    real: Callable[..., Any],
    main_ident: int,
    violations: list[str],
) -> Callable[..., Any]:
    def guarded(*args: Any, **kwargs: Any) -> Any:
        if threading.get_ident() == main_ident:
            target = args[0] if args else kwargs.get("path")
            violations.append(f"{name}({target!r})")
            raise MainThreadFsViolation(
                f"main-thread {name}({target!r}) inside a guarded block"
            )
        return real(*args, **kwargs)

    return guarded


@contextlib.contextmanager
def main_thread_fs_guard() -> Iterator[list[str]]:
    """Record and fail ``stat``/``lstat``/``scandir``/``resolve`` on this thread.

    Yields the list of violations; it stays empty when the block did no
    filesystem metadata I/O on the entering thread.
    """
    main_ident = threading.get_ident()
    violations: list[str] = []
    with (
        mock.patch.object(
            os, "stat", _guarded("os.stat", os.stat, main_ident, violations)
        ),
        mock.patch.object(
            os, "lstat", _guarded("os.lstat", os.lstat, main_ident, violations)
        ),
        mock.patch.object(
            os, "scandir", _guarded("os.scandir", os.scandir, main_ident, violations)
        ),
        mock.patch.object(
            Path,
            "resolve",
            _guarded("Path.resolve", Path.resolve, main_ident, violations),
        ),
    ):
        yield violations


__all__ = ["MainThreadFsViolation", "main_thread_fs_guard"]
