"""Child-side spans for the terminal artifact viewer.

When ``SASE_TUI_TRACE`` is not ``1`` this module is a near-zero-cost no-op
and imports nothing heavy. Enabled writes go through the existing TUI JSONL
trace sink.
"""

from __future__ import annotations

import os
import time
from typing import Any

_ENV_FLAG = "SASE_TUI_TRACE"
_OPEN_ID_ENV = "SASE_ARTIFACT_VIEWER_OPEN_ID"
_OPEN_T0_ENV = "SASE_ARTIFACT_VIEWER_OPEN_T0"

_child_start = time.perf_counter()
_first_visual_emitted = False


def _emit_child_span(name: str, *, mode: str, **fields: Any) -> None:
    """Emit ``artifact_viewer.<name>`` when child tracing is enabled."""

    if os.environ.get(_ENV_FLAG) != "1":
        return
    from sase.ace.tui.util.trace import trace_event

    elapsed_ms = (time.perf_counter() - _child_start) * 1000.0
    payload: dict[str, Any] = {
        "span": f"artifact_viewer.{name}",
        "mode": mode,
        "elapsed_ms": elapsed_ms,
    }
    open_id = os.environ.get(_OPEN_ID_ENV)
    if open_id:
        payload["open_id"] = open_id
    raw_t0 = os.environ.get(_OPEN_T0_ENV)
    if raw_t0:
        try:
            payload["since_select_ms"] = (time.time() - float(raw_t0)) * 1000.0
        except ValueError:
            pass
    payload.update(fields)
    trace_event(f"artifact_viewer.{name}", **payload)


def mark_child_ready(mode: str) -> None:
    """Record that the pane child finished imports and config resolution."""

    _emit_child_span("child_ready", mode=mode)


def mark_first_visual(mode: str) -> None:
    """Record the first successful ``kitten icat`` in this child process."""

    global _first_visual_emitted
    if _first_visual_emitted:
        return
    _first_visual_emitted = True
    _emit_child_span("first_visual", mode=mode)
