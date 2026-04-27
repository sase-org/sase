"""Scoped span tracer for the ace TUI hot paths.

Phase 1 of plans/202604/tui_perf_overhaul_1.md (bead sase-w.1). Provides a
``tui_trace(name, **counters)`` context manager that emits one JSONL line
per span to ``~/.sase/perf/tui_trace.jsonl`` (override with
``SASE_TUI_TRACE_PATH``), gated by ``SASE_TUI_TRACE=1``. When the env flag
is unset the context manager is a near-zero-cost no-op so spans can be
sprinkled across hot paths in production builds.

Each emitted record is a JSON object with at minimum::

    {
        "ts": <unix epoch seconds, float>,
        "span": "<dotted span name>",
        "duration_ms": <float>,
        "current_tab": "<tab name>" | null,
    }

plus any keyword counters supplied at the call site (e.g. ``count``,
``bytes_read``, ``options``). The TUI app also threads ``current_tab`` and
``current_idx`` into the global trace context via :func:`set_trace_context`
so downstream consumers can correlate spans with where the cursor was.

Counters are merged in this order (later wins): module defaults, global
context, per-call kwargs.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from collections.abc import Generator

log = logging.getLogger(__name__)

ENV_FLAG = "SASE_TUI_TRACE"
ENV_PATH = "SASE_TUI_TRACE_PATH"

_context: dict[str, Any] = {}


def is_enabled() -> bool:
    """Return True when ``SASE_TUI_TRACE=1`` is set in the environment."""
    return os.environ.get(ENV_FLAG) == "1"


def _trace_log_path() -> Path:
    """Return the JSONL path for trace samples (env-overridable)."""
    override = os.environ.get(ENV_PATH)
    if override:
        return Path(override)
    return Path.home() / ".sase" / "perf" / "tui_trace.jsonl"


def set_trace_context(**fields: Any) -> None:
    """Update the global trace context merged into every emitted span.

    Pass ``current_tab=...``, ``current_idx=...``, etc. Pass ``None`` to
    clear a field. Cheap to call when tracing is disabled — the values
    are still stored but never read.
    """
    for key, value in fields.items():
        if value is None:
            _context.pop(key, None)
        else:
            _context[key] = value


def _write(record: dict[str, Any]) -> None:
    path = _trace_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError as e:
        log.debug("trace log write failed: %s", e)


def trace_event(event: str, **fields: Any) -> None:
    """Emit a single point-in-time trace record when ``SASE_TUI_TRACE=1``.

    Used by selection-mutation call sites that don't span time (e.g. the
    moment ``current_idx`` is reassigned, or a widget's ``watch_highlighted``
    fires). Disabled-path overhead is one env lookup.
    """
    if not is_enabled():
        return
    record: dict[str, Any] = {
        "ts": time.time(),
        "event": event,
        "current_tab": _context.get("current_tab"),
    }
    for key, value in _context.items():
        if key == "current_tab":
            continue
        record.setdefault(key, value)
    record.update(fields)
    _write(record)


@contextmanager
def tui_trace(span: str, **counters: Any) -> Generator[None, None, None]:
    """Record a scoped phase span when ``SASE_TUI_TRACE=1`` is set.

    Use as::

        with tui_trace("changespec.refresh_display", count=len(specs)):
            ...

    Disabled-path overhead is one env lookup (cached by the OS) and a
    function-call frame; no allocations, no I/O, no time samples.
    """
    if not is_enabled():
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - started) * 1000.0
        record: dict[str, Any] = {
            "ts": time.time(),
            "span": span,
            "duration_ms": duration_ms,
            "current_tab": _context.get("current_tab"),
        }
        for key, value in _context.items():
            if key == "current_tab":
                continue
            record.setdefault(key, value)
        record.update(counters)
        _write(record)
