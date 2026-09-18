"""Process-start clocks for the pre-mount startup telemetry split.

``tui_startup.jsonl``'s ``process_start_to_on_mount_seconds`` keeps its
historical meaning (AceApp init stamp → ``on_mount``). These clocks add four
additive fields covering OS process start through ``compose()``:

- ``interpreter_cli_import_seconds``
- ``app_module_import_seconds``
- ``app_construct_seconds``
- ``compose_seconds``
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator
from typing import Any

_process_start_mono: float | None = None
_cli_ready_mono: float | None = None
_app_imported_mono: float | None = None
_app_construct_start_mono: float | None = None
_app_construct_end_mono: float | None = None
_compose_start_mono: float | None = None
_compose_end_mono: float | None = None


def _monotonic_at_os_process_start() -> float:
    """Best-effort monotonic timestamp of OS process start (Linux)."""
    now = time.monotonic()
    try:
        ticks = os.sysconf("SC_CLK_TCK")
        stat = Path("/proc/self/stat").read_text(encoding="utf-8")
        after_comm = stat[stat.rfind(")") + 2 :].split()
        start_boot_s = int(after_comm[19]) / ticks
        boottime_now = time.clock_gettime(time.CLOCK_BOOTTIME)
        age = boottime_now - start_boot_s
        if 0 <= age <= boottime_now:
            return now - age
    except (OSError, ValueError, IndexError, AttributeError):
        pass
    return now


def _ensure_process_start() -> float:
    global _process_start_mono
    if _process_start_mono is None:
        _process_start_mono = _monotonic_at_os_process_start()
    return _process_start_mono


def mark_cli_ready() -> None:
    """Stamp the end of interpreter + CLI import (just before AceApp import)."""
    global _cli_ready_mono
    _ensure_process_start()
    if _cli_ready_mono is None:
        _cli_ready_mono = time.monotonic()


def mark_app_imported() -> None:
    """Stamp the end of ``from sase.ace.tui import AceApp``."""
    global _app_imported_mono
    if _cli_ready_mono is None:
        mark_cli_ready()
    if _app_imported_mono is None:
        _app_imported_mono = time.monotonic()


def _mark_app_construct_start() -> None:
    """Stamp the start of ``AceApp()`` construction."""
    global _app_construct_start_mono
    if _app_construct_start_mono is None:
        _app_construct_start_mono = time.monotonic()


def _mark_app_construct_end() -> None:
    """Stamp the end of ``AceApp()`` construction."""
    global _app_construct_end_mono
    _app_construct_end_mono = time.monotonic()


def _mark_compose_start() -> None:
    """Stamp the start of ``AceApp.compose`` consumption."""
    global _compose_start_mono
    if _compose_start_mono is None:
        _compose_start_mono = time.monotonic()


def _mark_compose_end() -> None:
    """Stamp the end of ``AceApp.compose`` consumption."""
    global _compose_end_mono
    _compose_end_mono = time.monotonic()


@contextmanager
def app_constructing() -> Iterator[None]:
    """Measure ``AceApp.__init__`` including ``App.__init__``."""
    _mark_app_construct_start()
    try:
        yield
    finally:
        _mark_app_construct_end()


@contextmanager
def composing() -> Iterator[None]:
    """Measure Textual's consumption of ``compose()``."""
    _mark_compose_start()
    try:
        yield
    finally:
        _mark_compose_end()


def _since(start: float | None, end: float | None) -> float | None:
    if start is None or end is None:
        return None
    return round(end - start, 6)


def pre_mount_split_fields() -> dict[str, Any]:
    """Return the four additive pre-mount fields for the startup JSONL record."""
    _ensure_process_start()
    return {
        "interpreter_cli_import_seconds": _since(_process_start_mono, _cli_ready_mono),
        "app_module_import_seconds": _since(_cli_ready_mono, _app_imported_mono),
        "app_construct_seconds": _since(
            _app_construct_start_mono, _app_construct_end_mono
        ),
        "compose_seconds": _since(_compose_start_mono, _compose_end_mono),
    }
